from datetime import datetime
from backend.flashcard_library import flashcard as f
from backend.flashcard_library import library as l

class SessionQueue():
    def __init__(self, spaced_repetition):
        self.list_size = 0
        self.queue_size = 0
        self.items = []
        self.rear_pointer = -1
        self.front_pointer = -1
        self.spaced_repetition = spaced_repetition
    
    def isEmpty(self):
        return self.queue_size == 0
    
    def addFlashcard(self, flashcard):
        self.items.append(flashcard)
        self.rear_pointer = self.rear_pointer + 1
        self.queue_size += 1
        self.list_size += 1
    
    def getNextFlashcard(self):
        '''
        Dequeues a flashcard from the priority queue based on whether its "next_review" date attribute has passed
        '''
        if not self.isEmpty():
            
            self.front_pointer = (self.front_pointer + 1) % self.list_size

            if self.spaced_repetition:
             
                if str(self.items[self.front_pointer].next_review) <= str(datetime.now().date()) or not self.items[self.front_pointer].next_review:
                    return self.items[self.front_pointer]
                elif self.items[self.front_pointer].in_session:
                    self.queue_size -= 1
                    self.items[self.front_pointer].in_session = False
                    return self.getNextFlashcard()
                else:
                    return self.getNextFlashcard()
            else:
                return self.items[self.front_pointer]
        else:
            return None
    
    
    def getCurrentFlashcard(self):
        return self.items[self.front_pointer]