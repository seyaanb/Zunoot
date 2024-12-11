import backend.queries as q
from backend.flashcard_library import node as n, subject as s, topic as t, flashcard as f
import backend.session_queue as sq

classes = {
    "Library": s.Subject,
    "Subject": t.Topic,
    "Topic": f.Flashcard
}

class Library():

    def __init__(self, username):
        self.current_node = self
        self.__root = self
        self.children = []
        self.__username = username

    def goBack(self):
        self.current_node = self.current_node.getParent() 

    def updateCurrentNode(self, child):
        self.current_node = child
    
    def initialiseLibrary(self, username):
        '''
        iterates through the user's subjects from the database, instantiating a Subject object for each and 
        appending each to the library's children array.
        '''

        self.children = []
        subjects = q.get_children("Library", username)
        for subject in subjects:
            if subject:
                subject_object = s.Subject(*subject, self)
                self.children.append(subject_object)
                self.initialiseSubjects(subject_object)
    
    def initialiseSubjects(self, subject_object):
        '''
        iterates through the subject's topics from the database, instantiating a Topic object for each and 
        appending each to the subject's children array.
        '''
        topics = q.get_children("Subject", subject_object.subject_id)
        for topic in topics:
            if topic:
                topic_object = t.Topic(*topic, subject_object)
                subject_object.children.append(topic_object)
                self.initialiseTopics(topic_object)
            
    def initialiseTopics(self, topic_object):
        '''
        iterates through the topics's flashcards from the database, instantiating a Flashcard object for each and 
        appending each to the topics's children array.
        '''
        flashcards = q.get_children("Topic", topic_object.topic_id)
        for flashcard in flashcards:
            if flashcard:
                flashcard_object = f.Flashcard(*flashcard, topic_object)
                topic_object.children.append(flashcard_object)

    
    def getChildren(self):
        return self.children
    
    def resetChildren(self):
        self.children = []
    
    def addChild(self, name):
        q.add_subject(name, self.__username)

    def getCurrentNodeClass(self):
        return self.current_node.__class__.__name__
    
    def getChildByName(self, name):
        for child in self.children:
            if child.getName() == name:
                return child
        return None
    
    def getChildByID(self, id):
        for child in self.children:
            if int(child.subject_id) == int(id):
                return child
        return None
    
    def searchNode(self, node, keyword, s_list, t_list, f_list):
        '''
        params:
            node: the current node being operated upon
            keyword: the string searched for by the user
            s_list: the list of subjects whose name contains the keyword
            t_list: the list of topics whose name contains the keyword
            f_list: the list of flashcards whose front or back contains the keyword

        if node is a subject, topic or flashcard, its name (or front and back) are searched for the keyword
        the node's children are then recursively called and checked, until the node is a flashcard (i.e. a leaf node)
        '''
        if isinstance(node, Library):
            for child in node.children:
                self.searchNode(child, keyword, s_list, t_list, f_list)
        elif isinstance(node, s.Subject):
            if keyword.lower() in node.getName().lower():
                s_list.append(node)
            for child in node.children:
                self.searchNode(child, keyword, s_list, t_list, f_list)
        elif isinstance(node, t.Topic):
            if keyword.lower() in node.getName().lower():
                t_list.append(node)
            for child in node.children:
                self.searchNode(child, keyword, s_list, t_list, f_list)
        elif isinstance(node, f.Flashcard):
            if keyword.lower() in node.getName().lower() or keyword.lower() in node.getBack().lower():
                f_list.append(node)
    
    def searchLibrary(self, keyword):
        '''
        the searchNode algorithm is called, with the entire library being the initial node called upon
        lists of subjects, topics and flashcards containing the keyword are returned
        '''
        s_list = []
        t_list = []
        f_list = []

        self.searchNode(self, keyword, s_list, t_list, f_list)

        return s_list, t_list, f_list
    
    def traverseSubtree(self, current, flashcards):
        '''
        recursive function which retrieves all leaf nodes (flashcards) through a preorder traversal
        '''
        for child in current.children:
            if isinstance(child, f.Flashcard):
                flashcards.append(child)
            else:
                self.traverseSubtree(child, flashcards)

    def getLeafFlashcards(self):
        flashcards = []

        self.traverseSubtree(self.current_node, flashcards)

        return flashcards
    
    def makeSessionQueue(self, spaced_repetition):
        '''
        instantiates a Queue object and returns it
        '''
        queue = sq.SessionQueue(spaced_repetition)
        flashcards = self.getLeafFlashcards()

        for flashcard in flashcards:
            queue.addFlashcard(flashcard)

        return queue