class Credit:

    # fixed vocabulary for a credit's role, seeding credit_role_enum -- "actor" covers both actors
    # and actresses (IMDb's own fullcredits page doesn't distinguish them either, both are listed
    # under "Cast"). See ScrapeIMDbOnline.scrapeFullCredits.
    creditRoleList = ["director", "writer", "actor"]

    def __init__(self, person_id, ordering, creditRole, creditDetails=None):
        self.person_id = person_id
        self.ordering = ordering # this credit's position in the page's overall director(s)/writer(s)/actor(s) sequence, unique per medium
        self.creditRole = creditRole # one of Credit.creditRoleList
        self.creditDetails = creditDetails # character name for actors; credit qualifier text (e.g. "(story by)", "(uncredited)") for any role, when IMDb shows one; None otherwise

    def __str__(self):
        return str(self.ordering) + " " + self.creditRole + " nm" + str(self.person_id).zfill(7) + (" (" + str(self.creditDetails) + ")" if self.creditDetails else "")
