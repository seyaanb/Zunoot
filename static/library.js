const newSubjectButton = document.getElementById("newSubjectButton");
const addForm = document.getElementById("addForm");
const editButtons = document.querySelectorAll(".edit-button");
const reviewOptions = document.getElementById("reviewOptions");
const reviewButton = document.getElementById("reviewButton");
const revealFlashcard = document.querySelectorAll(".reveal-flashcard");

revealFlashcard.forEach(button => {
    button.addEventListener("click", () => {
        const flashcard = button.closest(".flashcard");
        if (flashcard) {
            const flashcardAnswer = flashcard.querySelector(".flashcard-answer");
            if (flashcardAnswer.style.display === "none") {
                flashcardAnswer.style.display = "block";
                button.innerHTML = "Hide Answer";
            } else {
                flashcardAnswer.style.display = "none";
                button.innerHTML = "Show Answer";
            }
        }
        
    });
});

reviewButton.addEventListener("click", () => {
    if (reviewOptions.style.display === "none") {
        reviewOptions.style.display = "block";
    } else {
        reviewOptions.style.display = "none";
    }
});

newSubjectButton.addEventListener("click", () => {
    newSubjectButton.style.display = "none";
    addForm.style.display = "block";

});

editButtons.forEach((button, index) => {
    button.addEventListener("click", () => {
        const parentItem = button.closest('li');
        const optionsMenu = parentItem.querySelector('.options-menu');
        const editForm = parentItem.querySelector('.edit-form');
        const link = parentItem.querySelector('.link');

        optionsMenu.style.display = "none";
        link.style.display = "none";
        editForm.style.display = "block";
    });
})



document.querySelectorAll('input[type="text"]').forEach(input => {
    input.addEventListener('keydown', function(event) {
        if (event.key === 'Enter') {
            event.preventDefault();
            input.form.submit();
        }
    });
});

document.addEventListener("DOMContentLoaded", () => {
    const subjectsList = document.getElementById("subjectsList");
    const topicsList = document.getElementById("topicsList");
    const flashcardsList = document.getElementById("flashcardsList");

    if (subjectsList) {
        new Sortable(subjectsList, {
            animation: 150,
            onEnd: async function(event) {
                await updateOrder(event);
            }
        });
    }

    if (topicsList) {
        new Sortable(topicsList, {
            animation: 150,
            onEnd: async function(event) {
                await updateOrder(event);
            }
        });
    }

    if (flashcardsList) {
        new Sortable(flashcardsList, {
            animation: 150,
            onEnd: async function(event) {
                await updateOrder(event);
            }
        });
    }

    async function updateOrder(event) {
        const itemType = event.item.getAttribute("data-type");
        const items = event.to.children;
        let order = [];

        for (let i = 0; i < items.length; i++) {
            order.push({
                id: items[i].getAttribute("data-id"),
                position: i
            });
        };

        try {
            const response = await fetch(`/library/update-order/${itemType}`, {
                method: "POST",
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ order })
            });
    
            if (!response.ok) {
                throw new Error("Network response was not ok");
            }
    
            const result = await response.json();
            console.log("Order updated successfully:", result);
        } catch (error) {
            console.error("Error updating order:", error);
        }
    }    
});

