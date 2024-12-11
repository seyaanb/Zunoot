from abc import ABC, abstractmethod

class Node(ABC):
    def __init__(self, parent):
        self.__parent_object = parent
        self.children = []

    def getParent(self):
        return self.__parent_object
    
    def resetChildren(self):
        self.children = []
    
    def getChildren(self):
        return self.children
    
    def getChildByName(self, name):
        for child in self.children:
            if child.getName() == name:
                return child
        return None
    
    def getChildByID(self, id):
        for child in self.children:
            if int(child.getID()) == int(id):
                return child
        return None
    
    @abstractmethod
    def getName(self):
        pass

    @abstractmethod
    def getID(self):
        pass
    



