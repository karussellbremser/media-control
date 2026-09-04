class Credit:

    # fixed vocabulary for a credit's role, seeding credit_role_enum -- "actor" covers both actors
    # and actresses (IMDb's own fullcredits page doesn't distinguish them either, both are listed
    # under "Cast"). See ScrapeIMDbOnline.scrapeFullCredits.
    creditRoleList = ["director", "writer", "actor"]

    def __init__(self, person_id, ordering, credit_role, credit_details=None):
        self.person_id = person_id
        self.ordering = ordering # this credit's position within its own role's list (restarts at 1 for each of director(s)/writer(s)/actor(s)), unique per medium+role
        self.credit_role = credit_role # one of Credit.creditRoleList
        self.credit_details = credit_details # character name for actors; credit qualifier text (e.g. "(story by)", "(uncredited)") for any role, when IMDb shows one; None otherwise

    def __str__(self):
        return str(self.ordering) + " " + self.credit_role + " nm" + str(self.person_id).zfill(7) + (" (" + str(self.credit_details) + ")" if self.credit_details else "")
