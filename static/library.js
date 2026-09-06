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

        const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

        try {
            const response = await fetch(`/library/update-order/${itemType}`, {
                method: "POST",
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
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