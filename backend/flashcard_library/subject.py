from backend.flashcard_library import node as n
from backend import queries as q

class Subject(n.Node):
    def __init__(self, subject_id, subject_name, username, position, parent):
        super().__init__(parent)
        self.subject_id = subject_id
        self.__name = subject_name
    
    def getName(self):
        return self.__name
    
    def getID(self):
        return self.subject_id
    
    def addChild(self, topic_name):
        q.add_topic(topic_name, self.subject_id)
    
    def editName(self, new_name):
        q.edit_subject_name(self.subject_id, new_name)
    
    def deleteSubject(self):
        q.delete_subject(self.subject_id)