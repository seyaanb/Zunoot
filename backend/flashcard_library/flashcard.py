from datetime import datetime, timedelta
from backend.flashcard_library import node as n
from backend import queries as q
from backend import session_queue as sq

class Flashcard(n.Node):
    def __init__(self, flashcard_id, front, back, interval, repetition_no, easiness_factor, last_review, next_review, topic_id, position, parent):
        super().__init__(parent)
        self.flashcard_id = flashcard_id
        self.__front = front
        self.__back = back
        self.interval = interval
        self.repetition_no = repetition_no
        self.easiness_factor = easiness_factor
        self.last_review = last_review
        self.next_review = next_review
        self.in_session = True
        self.__topic_id = topic_id
        self.__position = position

    def getName(self):
        return self.__front

    def getBack(self):
        return self.__back
    
    def getID(self):
        return self.flashcard_id
    
    def setPosition(self, new_position):
        self.__position = new_position
    
    def updateLastReview(self):
        self.last_review = datetime.now().date()
    
    def updateNextReview(self):
        self.next_review = self.last_review + timedelta(days=self.interval)
    
    def reviewFlashcard(self, option):
        '''
        applies the SM2 algorithm for spaced repetition.
        
        param option: user's ranking of the flashcard's difficulty from 0 to 5 (0 being extremely difficult and 5 being extremely easy)
        
        the number of days in which the flashcard should be shown next is updated based on the user's ranking, the number of times it 
        has been reviewed, and its calculated "easiness" factor
        '''
        option = int(option)
        if option >= 3:
            if self.repetition_no == 0:
                self.interval = 1
            elif self.repetition_no == 1:
                self.interval = 6
            else:
                self.interval = round(self.interval * self.easiness_factor)
            self.repetition_no += 1
        else:
            self.repetition_no = 0
            self.interval = 0

        self.easiness_factor = self.easiness_factor + (0.1 - (5 - option) * (0.08 + (5 - option) * 0.02))
        if self.easiness_factor < 1.3:
            self.easiness_factor = 1.3
        
        self.updateLastReview()
        self.updateNextReview()
    
    def editFlashcard(self, front, back):
        q.edit_flashcard(self.flashcard_id, front, back)
    
    def deleteFlashcard(self):
        q.delete_flashcard(self.flashcard_id)

