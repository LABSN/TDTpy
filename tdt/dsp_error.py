class DSPError(BaseException):

    def __init__(self, device, mesg):
        #self.error = error
        #if self.error == '':
            #self.error = "No error code returned"
        self.device = device
        self.mesg = mesg

    def __str__(self):
        #return '%s: %s (zBUS error code: %s)' % (self.device, self.mesg,
        #        self.error)
        return '{}: {}'.format(self.device, self.mesg)