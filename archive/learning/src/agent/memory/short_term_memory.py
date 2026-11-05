class ConversationMessage:
    def __init__(self):
        self.message = []

    def get_message(self):
        return self.message
    
    def clear_message(self):
        self.message = []

    def add_message(self,message):
        self.message.append(message)
