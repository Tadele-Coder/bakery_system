document.addEventListener('DOMContentLoaded', function () {

    const container = document.getElementById(
        'ingredients-container'
    );

    const addButton = document.getElementById(
        'add-ingredient'
    );


    function createIngredientRow() {

        const firstRow = container.querySelector(
            '.ingredient-row'
        );

        const newRow = firstRow.cloneNode(true);


        // Clear ingredient selection
        const ingredientSelect = newRow.querySelector(
            'select[name="ingredient"]'
        );

        if (ingredientSelect) {
            ingredientSelect.selectedIndex = 0;
        }


        // Clear quantity
        const quantityInput = newRow.querySelector(
            'input[name="quantity"]'
        );

        if (quantityInput) {
            quantityInput.value = '';
        }


        container.appendChild(newRow);

    }


    addButton.addEventListener('click', function () {

        createIngredientRow();

    });


    container.addEventListener('click', function (event) {

        if (
            event.target.classList.contains(
                'remove-ingredient'
            )
        ) {

            const rows = container.querySelectorAll(
                '.ingredient-row'
            );


            // Keep at least one ingredient row
            if (rows.length > 1) {

                event.target
                    .closest('.ingredient-row')
                    .remove();

            }

        }

    });

});