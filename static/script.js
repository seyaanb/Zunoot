/* installing the service worker */
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/service-worker.js').then(registration => {
        console.log("SW registered");
        console.log(registration);
    }).catch(error => {
        console.log("SW registration failed");
        console.log(error)
    });
};

document.addEventListener("DOMContentLoaded", () => {
    /*menu button*/
    const menuButton = document.getElementById("menuButton");
    const links = document.getElementById("links");

    menuButton.addEventListener("click", () => {
        if (links.style.display === "flex") {
            links.style.display = "none";
        }
        else {
            links.style.display = "flex";
        }
    });

    /*guild requests tab*/
    const requestsHeading = document.getElementById("requestsHeading");
    const requestsList = document.querySelector(".requests-list");

    requestsHeading.addEventListener("click", () => {
        if (requestsList.style.display === "none") {
            requestsList.style.display = "block";
        } else {
            requestsList.style.display = "none";
        }
    });
});


function showAnswer() {
    const front = document.getElementById("front");
    const back = document.getElementById("back");
    const showAnswerButton = document.getElementById("showAnswerButton");
    const optionButtons = document.getElementById("optionButtons");

    front.style.display = "none";
    back.style.display ="block";
    showAnswerButton.style.display = "none";
    optionButtons.style.display = "block";
}

function selectOption(){
    front.style.display = "block";
    back.style.display ="none";
    showAnswerButton.style.display = "block";
    optionButtons.style.display = "none";
};


function redirectToShop(itemType) {
    window.location.href = `?item_type=${itemType}`;
};

function toggleDropdown() {
    const dropdownSubjects = document.querySelector(".dropdown-subjects");

    if (dropdownSubjects.style.display === "none") {
        dropdownSubjects.style.display = "block";
    } else {
        dropdownSubjects.style.display = "none"
    }
}

/*create guild button*/
const createGuildForm = document.querySelector(".create-guild-form");


document.getElementById("createGuildButton").onclick = function() {
    let createGuildForm = document.getElementById("createGuildForm");
    if (createGuildForm.style.display === "none") {
        createGuildForm.style.display = "block";
    } else {
        createGuildForm.style.display = "none";
    }
};

