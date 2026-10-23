from datetime import date, datetime

from backend.flashcard_library import flashcard as f


def _to_iso(value):
    return value.isoformat() if value else None


def _from_iso(value):
    return date.fromisoformat(value) if value else None


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

    def _isDue(self, flashcard):
        return not flashcard.next_review or str(flashcard.next_review) <= str(datetime.now().date())

    def getNextFlashcard(self):
        '''
        Dequeues a flashcard from the circular queue. In spaced-repetition mode,
        cards whose "next_review" date has not yet passed are skipped and removed
        from the session.

        This used to be recursive, one call per skipped card, which raised
        RecursionError for libraries with more than ~1,000 not-yet-due cards.
        It is now a loop with identical behaviour.
        '''
        while not self.isEmpty():
            self.front_pointer = (self.front_pointer + 1) % self.list_size
            current = self.items[self.front_pointer]

            if not self.spaced_repetition or self._isDue(current):
                return current
            if current.in_session:
                self.queue_size -= 1
                current.in_session = False
        return None

    def getCurrentFlashcard(self):
        return self.items[self.front_pointer]

    # -- session (de)serialisation ------------------------------------------
    # Flask-Session 0.8 serialises sessions with msgspec, which only handles
    # plain data (dicts, lists, str, numbers). Storing this object directly made
    # every review request fail with a 500. The session now holds only card IDs
    # and their SM-2 state; card text is read from the database when displayed.

    def to_dict(self):
        return {
            "spaced_repetition": self.spaced_repetition,
            "front_pointer": self.front_pointer,
            "rear_pointer": self.rear_pointer,
            "queue_size": self.queue_size,
            "list_size": self.list_size,
            "items": [
                [card.flashcard_id, card.interval, card.repetition_no, float(card.easiness_factor),
                 _to_iso(card.last_review), _to_iso(card.next_review), card.in_session]
                for card in self.items
            ],
        }

    @classmethod
    def from_dict(cls, data):
        queue = cls(data["spaced_repetition"])
        queue.front_pointer = data["front_pointer"]
        queue.rear_pointer = data["rear_pointer"]
        queue.queue_size = data["queue_size"]
        queue.list_size = data["list_size"]
        for flashcard_id, interval, repetition_no, easiness, last_review, next_review, in_session in data["items"]:
            card = f.Flashcard(flashcard_id, None, None, interval, repetition_no, easiness,
                               _from_iso(last_review), _from_iso(next_review), None, None, None)
            card.in_session = in_session
            queue.items.append(card)
        return queue
