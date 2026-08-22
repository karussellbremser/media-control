class MediaSource:

    def __init__(self, role, source_type, disc_id=None, disc_corrected=False, web_provider=None,
                 base_layer=False, downmixed=False, core=False, fanres=False, seq=1):
        self.role = role
        self.source_type = source_type
        self.disc_id = disc_id
        self.disc_corrected = disc_corrected
        self.web_provider = web_provider
        self.base_layer = base_layer
        self.downmixed = downmixed
        self.core = core
        self.fanres = fanres
        self.seq = seq

    def __str__(self):
        return self.role + ":" + self.source_type + str(" " + str(self.disc_id) if self.disc_id is not None else "") + str(" " + self.web_provider if self.web_provider else "")

    def __eq__(self, other):
        return isinstance(other, MediaSource) and self.__dict__ == other.__dict__
