from backend.flashcard_library import node as n
from backend import queries as q

class Topic(n.Node):

    def __init__(self, topic_id, topic_name, subject_id, position, parent):
        super().__init__(parent)
        self.topic_id = topic_id
        self.__name = topic_name
        self.__subject_id = subject_id
        self.position = position

    def getName(self):
        return self.__name
    
    def getID(self):
        return self.topic_id
    
    def addChild(self, front, back):
        q.add_flashcard(front, back, self.topic_id)

    def editName(self, new_name):
        q.edit_topic_name(self.topic_id, new_name)
    
    def deleteTopic(self):
        q.delete_topic(self.topic_id)
    