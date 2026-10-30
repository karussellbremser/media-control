"""Deploys the web UI to the server it is hosted on (see README.md, "Hosting the web UI with Docker").

    python deploy.py status                     what runs on the server vs. what you have locally
    python deploy.py content [--prune]          new/changed covers and the current database
    python deploy.py code                       the server code (what is pushed to GitHub)
    python deploy.py full [--prune]             both, switched over together -- for code that needs a
                                                changed database format (e.g. a new column)
    python deploy.py rollback [--db]            back to the previous version (and, with --db, database)

Every command takes --dry-run (prints what it would change on the server, changes nothing) and -y/--yes
(no confirmation prompt). Connection details live in deploy.ini (copy deploy.example.ini).

What it does and checks:
  * The database is never copied live: a consistent snapshot is taken with SQLite's backup function and
    checked with integrity_check, and that snapshot is what gets uploaded.
  * Before anything reaches the server, the server code of your working tree is run against that snapshot
    (a smoke test of the pages, search, filters and detail views), so code and database that don't fit
    together are caught on this machine.
  * code/full deploy what is on GitHub: the server pulls it. Uncommitted changes to tracked files, or
    commits that aren't pushed yet, are refused (--skip-git-check overrides that).
  * Covers: the server's own file list is compared with yours (name, size, time); only new or changed
    files are sent, in one tar stream. Covers that exist on the server only are reported, and removed with
    --prune.
  * Database swap: uploaded as myMovieDB.db.new, checked by SHA-256, then renamed over the live file (atomic);
    the previous one is kept as myMovieDB.db.prev.
  * After a restart or a swap the result is verified: the container answers on its port, and the
    container's own user can read the database (row count must match) and the covers. If not, the previous
    version is restored automatically.
"""
import argparse
import configparser
import datetime
import hashlib
import os
import pathlib
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# names inside the server's data directory -- must match docker/config.docker.ini and compose.yaml
DATA_DIR = "data"
DB_NAME = "myMovieDB.db"
COVER_DIRS = ("covers_small", "covers")
HIDDEN_NAME = "hidden_interests.txt"
IMAGE = "media-control"  # compose.yaml's image name


class DeployError(Exception):
    pass


def step(message):
    print("\n== " + message)


def formatSize(num):
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return ("%d %s" % (num, unit)) if unit == "B" else ("%.1f %s" % (num, unit))
        num /= 1024.0


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------------------------------------- server

class Remote:
    """Runs commands on the server over ssh, always inside its project directory."""

    def __init__(self, section, dryRun):
        self.dry = dryRun
        self.target = section["user"] + "@" + section["host"]
        self.dir = section["remote_dir"]
        self.hostPort = int(section["host_port"])
        self.prefix = section.get("remote_prefix", "").strip()
        base = shlex.split(section.get("ssh_command", "ssh"))
        base += ["-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=15"]
        if section.get("port", "").strip():
            base += ["-p", section["port"].strip()]
        if section.get("identity_file", "").strip():
            base += ["-i", os.path.expanduser(section["identity_file"].strip())]
        self.sshBase = base

    def _wrap(self, command):
        full = "cd " + shlex.quote(self.dir) + " && " + command
        if self.prefix:
            full = self.prefix + " && " + full
        return "bash -lc " + shlex.quote(full)

    def sshArgs(self, command):
        return self.sshBase + [self.target, self._wrap(command)]

    def run(self, command, readonly=False, capture=False, check=True, stdin=None):
        """Runs command on the server. In a dry run, only readonly ones (listing, checking) really run;
        the rest is just printed. Returns a CompletedProcess (stdout as text if capture)."""
        if self.dry and not readonly:
            print("   [dry-run] on the server: " + command)
            return subprocess.CompletedProcess([], 0, "", "")
        result = subprocess.run(self.sshArgs(command), stdin=stdin, capture_output=capture, text=capture)
        if check and result.returncode != 0:
            raise DeployError("command failed on the server (exit " + str(result.returncode) + "): " + command +
                              ("\n" + result.stderr.strip() if capture and result.stderr else ""))
        return result

    def uploadFile(self, localPath, remotePath):
        if self.dry:
            print("   [dry-run] upload " + localPath + " -> " + remotePath)
            return
        with open(localPath, "rb") as f:
            self.run("cat > " + shlex.quote(remotePath), stdin=f)

    def uploadTar(self, localDir, names, remoteDir):
        """Sends the files `names` of localDir to remoteDir as one tar stream through a single ssh connection."""
        if self.dry:
            print("   [dry-run] send %d files from %s to %s as one tar stream" % (len(names), localDir, remoteDir))
            return
        tar = shutil.which("tar")
        if tar is None:
            raise DeployError("tar not found on this machine's PATH")
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, newline="\n") as f:
            f.write("\n".join(names) + "\n")
            listFile = f.name
        try:
            sender = subprocess.Popen([tar, "-cf", "-", "-C", localDir, "-T", listFile], stdout=subprocess.PIPE)
            receiver = subprocess.Popen(self.sshArgs("mkdir -p " + shlex.quote(remoteDir) + " && tar -xf - -C " + shlex.quote(remoteDir)),
                                        stdin=sender.stdout)
            sender.stdout.close()
            receiverCode = receiver.wait()
            senderCode = sender.wait()
        finally:
            os.remove(listFile)
        if senderCode != 0 or receiverCode != 0:
            raise DeployError("sending files to " + remoteDir + " failed (tar exit " + str(senderCode) + ", ssh/tar exit " + str(receiverCode) + ")")

    def listFiles(self, remoteDir):
        """{name: (size, mtime)} of the regular files directly in remoteDir ({} if it doesn't exist yet)."""
        out = self.run("[ -d " + shlex.quote(remoteDir) + " ] && find " + shlex.quote(remoteDir) +
                       " -maxdepth 1 -type f -printf '%f\\t%s\\t%T@\\n' || true", readonly=True, capture=True).stdout
        files = {}
        for line in out.splitlines():
            name, size, mtime = line.split("\t")
            files[name] = (int(size), float(mtime))
        return files


def checkRemote(remote):
    step("checking the connection to the server")
    result = remote.run("docker compose version > /dev/null && git --version > /dev/null && command -v curl > /dev/null && echo ready",
                        readonly=True, capture=True, check=False)
    if result.returncode != 0 or "ready" not in result.stdout:
        raise DeployError("can't use the server: ssh failed, or docker compose / git / curl isn't available in a non-interactive\n"
                          "shell there. If docker only works after some setup (e.g. exporting DOCKER_HOST for rootless docker),\n"
                          "put it in deploy.ini as remote_prefix.\n" + (result.stderr or "").strip())
    print("   ok")


# ----------------------------------------------------------------------------------------------- local

def localPaths(config):
    import serverconfig
    local = config["local"] if config.has_section("local") else {}
    return {
        "db": local.get("db_path") or serverconfig.DB_PATH,
        "covers": local.get("covers_dir") or serverconfig.COVERS_DIR,
        "covers_small": local.get("covers_small_dir") or serverconfig.COVERS_SMALL_DIR,
        "hidden": local.get("hidden_interest_ids_path") or serverconfig.HIDDEN_INTEREST_IDS_PATH,
    }


def snapshotDatabase(dbPath, outPath):
    """Consistent copy of the (possibly in-use) database, verified. Returns its row count in media."""
    step("snapshotting the database")
    try:
        source = sqlite3.connect(pathlib.Path(dbPath).resolve().as_uri() + "?mode=ro", uri=True)
        target = sqlite3.connect(outPath)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        check = sqlite3.connect(outPath)
        try:
            result = check.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise DeployError("the database snapshot failed SQLite's integrity_check (" + result + ") -- not deploying it")
            count = check.execute("SELECT COUNT(*) FROM media").fetchone()[0]
        finally:
            check.close()
    except sqlite3.Error as e:
        raise DeployError("the database can't be snapshotted (" + str(e) + ") -- not deploying it")
    print("   %s, integrity ok, %d rows in media" % (formatSize(os.path.getsize(outPath)), count))
    return count


def smokeTest(snapshotPath):
    """Runs this working tree's server code against the snapshot in a fresh interpreter (see _smoke)."""
    step("smoke-testing the server code against that database")
    result = subprocess.run([sys.executable, os.path.abspath(__file__), "_smoke", snapshotPath], capture_output=True, text=True)
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise DeployError("the smoke test failed -- this code does not work with this database:\n" + output)
    print("   " + output.splitlines()[-1])


def runSmoke(snapshotPath):
    """Child process of smokeTest: the real app, through Flask's test client, on the snapshot."""
    import serverconfig
    serverconfig.DB_PATH = snapshotPath
    import server
    server.AUTH_CREDENTIALS = None
    client = server.server.test_client()
    requests = 0

    def get(path):
        nonlocal requests
        response = client.get(path)
        requests += 1
        if response.status_code != 200:
            raise SystemExit("GET " + path + " -> " + str(response.status_code) + "\n" + response.get_data(as_text=True)[:400])
        return response

    get("/")
    rows = get("/search?movies=1&series=1").get_json()
    if not rows:
        raise SystemExit("the search returned no titles at all")
    con = sqlite3.connect(snapshotPath)
    genre = con.execute("""SELECT mi.imdb_interest_id FROM media_interests mi JOIN interest_enum e USING (imdb_interest_id)
                           WHERE e.parent_imdb_interest_id IS NULL GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 1""").fetchone()
    subgenre = con.execute("""SELECT mi.imdb_interest_id FROM media_interests mi JOIN interest_enum e USING (imdb_interest_id)
                              WHERE e.parent_imdb_interest_id IS NOT NULL GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 1""").fetchone()
    language = con.execute("SELECT language_code FROM media_languages WHERE ordering = 1 GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
    con.close()
    for sort in ("year", "title", "rating", "votes", "modified", "random"):
        get("/search?movies=1&series=1&sort=" + sort)
    get("/search?movies=1&q=the&year_from=1980&rating_from=5&votes_from=1000")
    if genre:
        get("/search?movies=1&genres[]=%d" % genre[0])
        get("/search?movies=1&notGenres[]=%d" % genre[0])
        if subgenre:
            get("/search?movies=1&genres[]=%d&interests[]=%d" % (genre[0], subgenre[0]))
    if language:
        get("/search?movies=1&series=1&language=" + language[0])
    series = get("/search?movies=0&series=1").get_json()
    for row in rows[:3] + series[:2]:
        get("/detail/%d" % row[0])
    print("smoke test passed (%d requests: pages, search with filters and every sort, detail views)" % requests)


def gitCheck(branch):
    """Refuses unless the working tree's tracked files are clean and HEAD is the pushed tip of branch.
    Returns (commit, subject) of what will be deployed."""
    step("checking that what's on GitHub is what you have")

    def git(*args):
        result = subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True)
        if result.returncode != 0:
            raise DeployError("git " + " ".join(args) + " failed: " + result.stderr.strip())
        return result.stdout.strip()

    dirty = git("status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise DeployError("uncommitted changes in tracked files (the server only gets what is pushed):\n" + dirty +
                          "\ncommit and push first, or use --skip-git-check")
    current = git("rev-parse", "--abbrev-ref", "HEAD")
    if current != branch:
        raise DeployError("you are on branch " + current + ", the server follows " + branch)
    git("fetch", "-q", "origin", branch)
    head, origin = git("rev-parse", "HEAD"), git("rev-parse", "origin/" + branch)
    if head != origin:
        ahead = git("rev-list", "--count", "origin/" + branch + "..HEAD")
        behind = git("rev-list", "--count", "HEAD..origin/" + branch)
        raise DeployError("HEAD is not the tip of origin/" + branch + " (" + ahead + " commit(s) not pushed, " + behind +
                          " not pulled) -- push first, or use --skip-git-check")
    subject = git("log", "-1", "--format=%s")
    print("   deploying " + head[:7] + " " + subject)
    return head, subject


# ------------------------------------------------------------------------------------- covers & database

def planCovers(remote, paths):
    """{subdir: (changed names, server-only names, bytes to send)} by comparing name, size and time."""
    plans = {}
    for sub in COVER_DIRS:
        localDir = paths[sub]
        local = {}
        if os.path.isdir(localDir):
            for entry in os.scandir(localDir):
                if entry.is_file():
                    stat = entry.stat()
                    local[entry.name] = (stat.st_size, stat.st_mtime)
        remoteFiles = remote.listFiles(DATA_DIR + "/" + sub)
        changed = sorted(name for name, (size, mtime) in local.items()
                         if name not in remoteFiles or remoteFiles[name][0] != size or mtime > remoteFiles[name][1] + 2)
        serverOnly = sorted(set(remoteFiles) - set(local))
        plans[sub] = (changed, serverOnly, sum(local[name][0] for name in changed))
    return plans


def describeCovers(plans, prune):
    lines = []
    for sub, (changed, serverOnly, size) in plans.items():
        text = "%s: %d new/changed (%s)" % (sub, len(changed), formatSize(size))
        if serverOnly:
            text += ", %d only on the server (%s)" % (len(serverOnly), "will be removed" if prune else "kept; --prune removes them")
        lines.append("   " + text)
        for name in changed[:5]:
            lines.append("      + " + name)
        if len(changed) > 5:
            lines.append("      + ... %d more" % (len(changed) - 5))
    return lines


def sendCovers(remote, paths, plans, prune):
    step("sending covers")
    for sub, (changed, serverOnly, size) in plans.items():
        if changed:
            print("   %s: %d files, %s" % (sub, len(changed), formatSize(size)))
            remote.uploadTar(paths[sub], changed, DATA_DIR + "/" + sub)
        else:
            print("   %s: up to date" % sub)
        if prune and serverOnly:
            print("   %s: removing %d files that only exist on the server" % (sub, len(serverOnly)))
            if not remote.dry:
                result = subprocess.run(remote.sshArgs("cd " + shlex.quote(DATA_DIR + "/" + sub) + " && xargs -d '\\n' rm -f --"),
                                        input=("\n".join(serverOnly) + "\n").encode("utf-8"))  # bytes: text mode would turn "\n" into CRLF on Windows
                if result.returncode != 0:
                    raise DeployError("removing server-only covers failed")
            else:
                print("   [dry-run] remove " + ", ".join(serverOnly[:5]) + (" ..." if len(serverOnly) > 5 else ""))


def uploadDatabase(remote, snapshotPath):
    step("uploading the database snapshot")
    remote.run("mkdir -p " + DATA_DIR)
    remote.uploadFile(snapshotPath, DATA_DIR + "/" + DB_NAME + ".new")
    if remote.dry:
        return
    out = remote.run("sha256sum " + shlex.quote(DATA_DIR + "/" + DB_NAME + ".new") + " | cut -d' ' -f1", capture=True).stdout.strip()
    if out != sha256(snapshotPath):
        raise DeployError("the uploaded database doesn't match the local snapshot (checksum) -- not swapping it in")
    print("   uploaded, checksum matches")


def hiddenInterestsChanged(remote, paths):
    """True if hidden_interests.txt differs from the server's (the server reads it only at start)."""
    if not os.path.isfile(paths["hidden"]):
        return False
    out = remote.run("sha256sum " + shlex.quote(DATA_DIR + "/" + HIDDEN_NAME) + " 2>/dev/null | cut -d' ' -f1", readonly=True, capture=True).stdout.strip()
    return out != sha256(paths["hidden"])


def swapDatabase(remote):
    """Keeps the live database as .prev and renames the uploaded one over it (atomic)."""
    base = shlex.quote(DATA_DIR + "/" + DB_NAME)
    remote.run("chmod -R a+rX " + DATA_DIR + " && { [ ! -f " + base + " ] || cp -p " + base + " " + base + ".prev; } && mv " + base + ".new " + base)


def restoreDatabase(remote):
    base = shlex.quote(DATA_DIR + "/" + DB_NAME)
    remote.run("[ -f " + base + ".prev ] && mv " + base + ".prev " + base)


# --------------------------------------------------------------------------------- verifying & rolling back

def healthCheck(remote):
    """Waits (up to ~40 s) for the container to answer on its host port: 401 (login required) or 200."""
    command = ("for i in $(seq 1 20); do code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:" + str(remote.hostPort) + "/); "
               "if [ \"$code\" = 401 ] || [ \"$code\" = 200 ]; then echo OK $code; exit 0; fi; sleep 2; done; echo FAIL $code; exit 1")
    result = remote.run(command, capture=True, check=False)
    return result.returncode == 0, result.stdout.strip()


def verifyRemote(remote, expectedRows, sampleCovers):
    """Checks from inside the running container, i.e. as the app's own user: the database opens and has
    the expected number of rows, and some covers are readable. Returns a list of problems (empty = fine)."""
    problems = []
    ok, message = healthCheck(remote)
    print("   answers on port %d: %s" % (remote.hostPort, message))
    if not ok:
        problems.append("the container doesn't answer on port " + str(remote.hostPort))
    code = ("import sqlite3; c = sqlite3.connect('file:/data/" + DB_NAME + "?mode=ro', uri=True); "
            "print(c.execute('SELECT COUNT(*) FROM media').fetchone()[0])")
    result = remote.run("docker compose exec -T " + IMAGE + " python -c " + shlex.quote(code), capture=True, check=False)
    try:
        rows = int(result.stdout.strip())
        print("   the app reads the database: %d rows in media" % rows)
        if expectedRows is not None and rows != expectedRows:
            problems.append("the app sees %d rows in media, expected %d (the new database isn't the one being served)" % (rows, expectedRows))
        if rows == 0:
            problems.append("the database the app reads is empty")
    except ValueError:
        problems.append("the app can't read the database: " + (result.stderr or result.stdout).strip()[-300:])
    if sampleCovers:
        code = "import sys; [open('/data/covers_small/' + n, 'rb').read(1) for n in sys.argv[1:]]; print('ok')"
        result = remote.run("docker compose exec -T " + IMAGE + " python -c " + shlex.quote(code) + " " + " ".join(shlex.quote(n) for n in sampleCovers),
                            capture=True, check=False)
        if "ok" in result.stdout:
            print("   the app reads covers (%d sampled)" % len(sampleCovers))
        else:
            problems.append("the app can't read covers (permissions?): " + (result.stderr or result.stdout).strip()[-300:])
    if problems:
        print("   PROBLEMS:\n      - " + "\n      - ".join(problems))
        logs = remote.run("docker compose logs --tail 25 2>&1", capture=True, check=False)
        print("   last log lines:\n" + "\n".join("      " + line for line in (logs.stdout or "").splitlines()))
    return problems


def rollbackCode(remote, restoreDb):
    """Previous image and (git) code, and optionally the previous database, back in place."""
    step("rolling back")
    parts = ["[ -f .git/deploy_previous_commit ]", "git reset -q --hard \"$(cat .git/deploy_previous_commit)\"",
             "docker tag " + IMAGE + ":previous " + IMAGE]
    if restoreDb:
        base = shlex.quote(DATA_DIR + "/" + DB_NAME)
        parts.append("{ [ ! -f " + base + ".prev ] || mv " + base + ".prev " + base + "; }")
    parts.append("docker compose up -d --no-build")
    remote.run(" && ".join(parts))


def sampleCoverNames(plans, paths):
    names = [n for sub in ("covers_small",) for n in plans.get(sub, ([], [], 0))[0][:3]]
    if not names and os.path.isdir(paths["covers_small"]):
        names = sorted(os.listdir(paths["covers_small"]))[:3]
    return names


# ------------------------------------------------------------------------------------------- commands

def confirm(args, lines):
    print("\nPlan:")
    for line in lines:
        print(line if line.startswith(" ") else "   " + line)
    if args.dry_run:
        print("\n(dry run: nothing below changes the server)")
        return
    if args.yes:
        return
    if input("\nProceed? [y/N] ").strip().lower() != "y":
        raise DeployError("cancelled")


def cmdStatus(remote, paths):
    checkRemote(remote)
    step("server")
    out = remote.run(
        "echo \"commit:      $(git rev-parse --short HEAD) $(git log -1 --format='%s (%cd)' --date=short)\"; "
        "echo \"database:    $(stat -c '%s bytes, %y' " + DATA_DIR + "/" + DB_NAME + " 2>/dev/null | cut -d. -f1)\"; "
        "echo \"previous db: $([ -f " + DATA_DIR + "/" + DB_NAME + ".prev ] && echo kept || echo none)\"; "
        "echo \"covers:      $(ls " + DATA_DIR + "/covers 2>/dev/null | wc -l) full size, $(ls " + DATA_DIR + "/covers_small 2>/dev/null | wc -l) small\"; "
        "echo \"container:   $(docker compose ps --format '{{.Name}} {{.Status}}' 2>/dev/null | head -1)\"", readonly=True, capture=True).stdout
    print(out.rstrip())
    step("this machine")
    head = subprocess.run(["git", "log", "-1", "--format=%h %s (%cd)", "--date=short"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    print("commit:      " + head)
    if os.path.isfile(paths["db"]):
        print("database:    %d bytes, %s" % (os.path.getsize(paths["db"]),
              datetime.datetime.fromtimestamp(os.path.getmtime(paths["db"])).strftime("%Y-%m-%d %H:%M:%S")))
    for sub in ("covers", "covers_small"):
        print("%-12s %d files" % (sub + ":", len(os.listdir(paths[sub])) if os.path.isdir(paths[sub]) else 0))


def cmdContent(args, remote, paths, branch, workDir):
    checkRemote(remote)
    snapshotPath = os.path.join(workDir, DB_NAME)
    rows = None
    if not args.skip_db:
        rows = snapshotDatabase(paths["db"], snapshotPath)
        smokeTest(snapshotPath)
    plans = {} if args.skip_covers else planCovers(remote, paths)
    restart = hiddenInterestsChanged(remote, paths)
    lines = []
    if not args.skip_covers:
        lines += describeCovers(plans, args.prune)
    if not args.skip_db:
        lines.append("database: upload the snapshot (%s) and switch it in; the old one stays as %s.prev" % (formatSize(os.path.getsize(snapshotPath)), DB_NAME))
    if restart:
        lines.append(HIDDEN_NAME + " changed: upload it and restart the container (a few seconds)")
    pruning = args.prune and any(serverOnly for _, serverOnly, _ in plans.values())
    if not any(changed for changed, _, _ in plans.values()) and args.skip_db and not restart and not pruning:
        print("\n" + "\n".join(line.strip() for line in lines if "only on the server" in line))
        print("nothing to do")
        return
    confirm(args, lines)

    if not args.skip_covers:
        sendCovers(remote, paths, plans, args.prune)
    if restart:
        step("uploading " + HIDDEN_NAME)
        remote.uploadFile(paths["hidden"], DATA_DIR + "/" + HIDDEN_NAME)
    if not args.skip_db:
        uploadDatabase(remote, snapshotPath)
        step("switching the database")
        swapDatabase(remote)
    else:
        remote.run("chmod -R a+rX " + DATA_DIR)
    if restart:
        remote.run("docker compose restart")
    if remote.dry:
        print("\n[dry-run] done; would verify the result from inside the container")
        return
    step("verifying")
    problems = verifyRemote(remote, rows, sampleCoverNames(plans, paths))
    if problems:
        if not args.skip_db:
            step("restoring the previous database")
            restoreDatabase(remote)
            verifyRemote(remote, None, [])
        raise DeployError("verification failed, previous database restored" if not args.skip_db else "verification failed")
    print("\ncontent deployed")


def remoteHead(remote):
    return remote.run("git rev-parse HEAD", readonly=True, capture=True).stdout.strip()


def pullAndTag(remote, expectedCommit):
    """Records the current server commit and image as 'previous', pulls, and checks it is the commit we meant."""
    remote.run("git rev-parse HEAD > .git/deploy_previous_commit && git pull -q --ff-only")
    if not remote.dry and expectedCommit is not None:
        got = remoteHead(remote)
        if got != expectedCommit:
            remote.run("git reset -q --hard \"$(cat .git/deploy_previous_commit)\"")
            raise DeployError("after the pull the server is at " + got[:7] + ", not " + expectedCommit[:7] +
                              " (someone pushed in between?) -- left at the previous commit")
    remote.run("docker tag " + IMAGE + ":latest " + IMAGE + ":previous 2>/dev/null || true")


def cmdCode(args, remote, paths, branch, workDir):
    checkRemote(remote)
    commit = subject = None
    if not args.skip_git_check:
        commit, subject = gitCheck(branch)
    snapshotPath = os.path.join(workDir, DB_NAME)
    snapshotDatabase(paths["db"], snapshotPath)
    smokeTest(snapshotPath)
    confirm(args, ["server: git pull" + (" (" + commit[:7] + " " + subject + ")" if commit else ""),
                   "rebuild the image and restart the container (a few seconds of downtime)",
                   "verify; restore the previous version automatically if that fails"])
    step("updating the server code")
    pullAndTag(remote, commit)
    result = remote.run("docker compose up -d --build", check=False)
    if result.returncode != 0:
        remote.run("git reset -q --hard \"$(cat .git/deploy_previous_commit)\"")
        raise DeployError("the build or start failed; the server was reset to its previous commit and the old container was not touched")
    if remote.dry:
        print("\n[dry-run] done; would verify the result from inside the container")
        return
    step("verifying")
    if verifyRemote(remote, None, sampleCoverNames({}, paths)):
        rollbackCode(remote, restoreDb=False)
        verifyRemote(remote, None, [])
        raise DeployError("verification failed, previous version restored")
    print("\ncode deployed")


def cmdFull(args, remote, paths, branch, workDir):
    checkRemote(remote)
    commit = subject = None
    if not args.skip_git_check:
        commit, subject = gitCheck(branch)
    snapshotPath = os.path.join(workDir, DB_NAME)
    rows = snapshotDatabase(paths["db"], snapshotPath)
    smokeTest(snapshotPath)
    plans = {} if args.skip_covers else planCovers(remote, paths)
    restart = hiddenInterestsChanged(remote, paths)
    lines = [] if args.skip_covers else describeCovers(plans, args.prune)
    lines += ["database: upload the snapshot (%s); it is switched in together with the new code" % formatSize(os.path.getsize(snapshotPath)),
              "server: git pull" + (" (" + commit[:7] + " " + subject + ")" if commit else "") + ", build the new image while the old one keeps serving",
              "then switch database and container over (a few seconds of downtime)",
              "verify; restore the previous code AND database automatically if that fails"]
    if restart:
        lines.append(HIDDEN_NAME + " changed: uploaded too")
    confirm(args, lines)

    if not args.skip_covers:
        sendCovers(remote, paths, plans, args.prune)
    if restart:
        step("uploading " + HIDDEN_NAME)
        remote.uploadFile(paths["hidden"], DATA_DIR + "/" + HIDDEN_NAME)
    uploadDatabase(remote, snapshotPath)
    step("building the new version (the old one keeps running)")
    pullAndTag(remote, commit)
    result = remote.run("docker compose build", check=False)
    if result.returncode != 0:
        remote.run("git reset -q --hard \"$(cat .git/deploy_previous_commit)\"")
        raise DeployError("the build failed; nothing was switched (the new database is uploaded as " + DB_NAME + ".new, the server was reset to its previous commit)")
    step("switching over")
    swapDatabase(remote)
    remote.run("docker compose up -d")
    if remote.dry:
        print("\n[dry-run] done; would verify the result from inside the container")
        return
    step("verifying")
    if verifyRemote(remote, rows, sampleCoverNames(plans, paths)):
        rollbackCode(remote, restoreDb=True)
        verifyRemote(remote, None, [])
        raise DeployError("verification failed, previous code and database restored")
    print("\ncode and database deployed")


def cmdRollback(args, remote):
    checkRemote(remote)
    if args.db and remote.run("[ -f " + shlex.quote(DATA_DIR + "/" + DB_NAME + ".prev") + " ]", readonly=True, check=False).returncode != 0:
        raise DeployError("there is no previous database on the server (" + DB_NAME + ".prev) -- nothing to restore")
    confirm(args, ["restore the previous image and git commit on the server" + (" and the previous database (" + DB_NAME + ".prev)" if args.db else ""),
                   "restart the container"])
    rollbackCode(remote, restoreDb=args.db)
    if not remote.dry:
        step("verifying")
        if verifyRemote(remote, None, []):
            raise DeployError("the server still has problems after the rollback")
    print("\nrolled back")


# ------------------------------------------------------------------------------------------------ main

def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=os.path.join(HERE, "deploy.ini"), help="connection settings (default: deploy.ini)")
    common.add_argument("--dry-run", action="store_true", help="show what would change on the server, change nothing")
    common.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")

    parser = argparse.ArgumentParser(description="Deploys the web UI to its server (options go after the command).")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("status", parents=[common], help="what runs on the server vs. here")
    content = commands.add_parser("content", parents=[common], help="new/changed covers and the current database")
    content.add_argument("--prune", action="store_true", help="also delete covers that only exist on the server")
    content.add_argument("--skip-db", action="store_true", help="covers only")
    content.add_argument("--skip-covers", action="store_true", help="database only")
    code = commands.add_parser("code", parents=[common], help="the server code, as pushed to GitHub")
    code.add_argument("--skip-git-check", action="store_true", help="don't insist that HEAD is pushed and clean")
    full = commands.add_parser("full", parents=[common], help="code and database together (for database format changes)")
    full.add_argument("--prune", action="store_true", help="also delete covers that only exist on the server")
    full.add_argument("--skip-covers", action="store_true", help="don't sync covers")
    full.add_argument("--skip-git-check", action="store_true", help="don't insist that HEAD is pushed and clean")
    rollback = commands.add_parser("rollback", parents=[common], help="back to the previous version")
    rollback.add_argument("--db", action="store_true", help="also restore the previous database")
    smoke = commands.add_parser("_smoke")  # internal: child process of the smoke test
    smoke.add_argument("snapshot")
    args = parser.parse_args()

    if args.command == "_smoke":
        runSmoke(args.snapshot)
        return 0

    if not os.path.isfile(args.config):
        print("no " + args.config + " -- copy deploy.example.ini to deploy.ini and fill it in")
        return 1
    config = configparser.ConfigParser()
    config.read(args.config, encoding="utf-8")
    remote = Remote(config["server"], args.dry_run)
    branch = config["server"].get("branch", "main")
    paths = localPaths(config)

    workDir = tempfile.mkdtemp(prefix="deploy-")
    try:
        if args.command == "status":
            cmdStatus(remote, paths)
        elif args.command == "content":
            cmdContent(args, remote, paths, branch, workDir)
        elif args.command == "code":
            cmdCode(args, remote, paths, branch, workDir)
        elif args.command == "full":
            cmdFull(args, remote, paths, branch, workDir)
        elif args.command == "rollback":
            cmdRollback(args, remote)
    except DeployError as e:
        print("\nERROR: " + str(e))
        return 1
    finally:
        shutil.rmtree(workDir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
