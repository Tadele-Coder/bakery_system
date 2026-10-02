document.addEventListener('DOMContentLoaded', function () {

    const container = document.getElementById(
        'ingredients-container'
    );

    const addButton = document.getElementById(
        'add-ingredient'
    );

    const productSelect = document.getElementById(
        'id_product'
    );

    if (!container || !addButton || !productSelect) {
        return;
    }


    /*
     * Keep a copy of the first ingredient row.
     * We use this as a template whenever we
     * need to create a new row.
     */
    const templateRow = container.querySelector(
        '.ingredient-row'
    ).cloneNode(true);


    /*
     * Create an empty ingredient row.
     */
    function createIngredientRow() {

        const newRow = templateRow.cloneNode(true);


        const ingredientSelect = newRow.querySelector(
            'select[name="ingredient"]'
        );

        if (ingredientSelect) {

            ingredientSelect.selectedIndex = 0;

        }


        const quantityInput = newRow.querySelector(
            'input[name="quantity"]'
        );

        if (quantityInput) {

            quantityInput.value = '';

        }


        container.appendChild(newRow);

        return newRow;
    }


    /*
     * Remove all existing ingredient rows.
     */
    function clearIngredientRows() {

        container.innerHTML = '';

    }


    /*
     * Add a recipe ingredient row.
     */
    function addIngredientRow(item) {

        const newRow = templateRow.cloneNode(true);


        const ingredientSelect = newRow.querySelector(
            'select[name="ingredient"]'
        );

        if (ingredientSelect) {

            ingredientSelect.value =
                String(item.ingredient_id);

        }


        const quantityInput = newRow.querySelector(
            'input[name="quantity"]'
        );

        if (quantityInput) {

            quantityInput.value =
                item.quantity;

        }


        container.appendChild(newRow);

    }


    /*
     * Load the recipe belonging to
     * the selected product.
     */
    function loadProductRecipe(productId) {

        if (!productId) {

            clearIngredientRows();

            createIngredientRow();

            return;

        }


        const url =
            `/recipes/product/${productId}/ingredients/`;


        fetch(url)

            .then(function (response) {

                if (!response.ok) {

                    throw new Error(
                        'Unable to load recipe.'
                    );

                }

                return response.json();

            })

            .then(function (data) {

                console.log(
                    'Recipe data:',
                    data
                );


                clearIngredientRows();


                /*
                 * No recipe exists for this product.
                 */
                if (
                    !data.recipe_exists ||
                    !data.ingredients ||
                    data.ingredients.length === 0
                ) {

                    createIngredientRow();

                    return;

                }


                /*
                 * Add all ingredients belonging
                 * to the selected product.
                 */
                data.ingredients.forEach(
                    function (item) {

                        addIngredientRow(item);

                    }
                );

            })

            .catch(function (error) {

                console.error(
                    'Recipe loading error:',
                    error
                );


                clearIngredientRows();

                createIngredientRow();

            });

    }


    /*
     * Product selection changed.
     */
    productSelect.addEventListener(
        'change',
        function () {

            loadProductRecipe(
                this.value
            );

        }
    );


    /*
     * Add ingredient button.
     */
    addButton.addEventListener(
        'click',
        function () {

            createIngredientRow();

        }
    );


    /*
     * Remove ingredient.
     */
    container.addEventListener(
        'click',
        function (event) {

            const removeButton =
                event.target.closest(
                    '.remove-ingredient'
                );


            if (!removeButton) {

                return;

            }


            const rows =
                container.querySelectorAll(
                    '.ingredient-row'
                );


            /*
             * Keep at least one row.
             */
            if (rows.length > 1) {

                removeButton
                    .closest('.ingredient-row')
                    .remove();

            }

        }
    );

});