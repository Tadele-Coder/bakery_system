document.addEventListener('DOMContentLoaded', function () {

    const addProductButton =
        document.getElementById('add-product');

    const productItems =
        document.getElementById('product-items');


    if (!addProductButton || !productItems) {
        return;
    }


    // --------------------------------------------------
    // Recipe Display
    // --------------------------------------------------

    function updateRecipeDisplay(row) {

        const select =
            row.querySelector('.product-select');

        const plannedQuantityInput =
            row.querySelector('input[name="planned_quantity"]');


        if (!select || !plannedQuantityInput) {
            return;
        }


        // Remove existing recipe information
        const existingRecipe =
            row.querySelector('.recipe-information');

        if (existingRecipe) {
            existingRecipe.remove();
        }


        const selectedOption =
            select.options[select.selectedIndex];


        if (!selectedOption || !selectedOption.value) {
            return;
        }


        const hasRecipe =
            selectedOption.dataset.hasRecipe === 'true';


        // Product has no recipe
        if (!hasRecipe) {

            const warning =
                document.createElement('div');

            warning.className =
                'recipe-information alert alert-warning mt-3';

            warning.innerHTML =
                '<i class="fa-solid fa-triangle-exclamation"></i> ' +
                '<strong>No Recipe:</strong> ' +
                'This product does not have a recipe yet.';

            row.appendChild(warning);

            return;
        }


        let recipe = [];

        try {

            recipe =
                JSON.parse(
                    selectedOption.dataset.recipe
                );

        } catch (error) {

            console.error(
                'Unable to read recipe information:',
                error
            );

            return;
        }


        if (!recipe.length) {

            const warning =
                document.createElement('div');

            warning.className =
                'recipe-information alert alert-warning mt-3';

            warning.innerHTML =
                '<i class="fa-solid fa-triangle-exclamation"></i> ' +
                '<strong>Recipe has no ingredients.</strong>';

            row.appendChild(warning);

            return;
        }


        const recipeBox =
            document.createElement('div');

        recipeBox.className =
            'recipe-information mt-3';


        const recipeTitle =
            document.createElement('h6');

        recipeTitle.className =
            'mb-2';

        recipeTitle.innerHTML =
            '<i class="fa-solid fa-utensils"></i> ' +
            'Required Ingredients';

        recipeBox.appendChild(recipeTitle);


        const table =
            document.createElement('div');

        table.className =
            'table-responsive';


        const tableElement =
            document.createElement('table');

        tableElement.className =
            'table table-sm table-bordered mb-0';


        tableElement.innerHTML =
            '<thead>' +
                '<tr>' +
                    '<th>Ingredient</th>' +
                    '<th>Per Unit</th>' +
                    '<th>Required Quantity</th>' +
                '</tr>' +
            '</thead>' +
            '<tbody></tbody>';


        const tbody =
            tableElement.querySelector('tbody');


        const plannedQuantity =
            parseFloat(
                plannedQuantityInput.value
            ) || 0;


        recipe.forEach(function (item) {

            const perUnit =
                parseFloat(item.quantity) || 0;

            const requiredQuantity =
                perUnit * plannedQuantity;


            const rowElement =
                document.createElement('tr');


            rowElement.innerHTML =
                '<td>' +
                    item.ingredient +
                '</td>' +

                '<td>' +
                    perUnit.toFixed(3) +
                    ' ' +
                    item.unit +
                '</td>' +

                '<td>' +
                    requiredQuantity.toFixed(3) +
                    ' ' +
                    item.unit +
                '</td>';


            tbody.appendChild(rowElement);

        });


        table.appendChild(tableElement);

        recipeBox.appendChild(table);

        row.appendChild(recipeBox);

    }


    // --------------------------------------------------
    // Product Selection
    // --------------------------------------------------

    productItems.addEventListener(
        'change',
        function (event) {

            if (
                event.target.classList.contains(
                    'product-select'
                )
            ) {

                const row =
                    event.target.closest(
                        '.production-item-row'
                    );

                if (row) {
                    updateRecipeDisplay(row);
                }

            }

        }
    );


    // --------------------------------------------------
    // Planned Quantity Changes
    // --------------------------------------------------

    productItems.addEventListener(
        'input',
        function (event) {

            if (
                event.target.name ===
                'planned_quantity'
            ) {

                const row =
                    event.target.closest(
                        '.production-item-row'
                    );

                if (row) {
                    updateRecipeDisplay(row);
                }

            }

        }
    );


    // --------------------------------------------------
    // Add a New Production Item
    // --------------------------------------------------

    addProductButton.addEventListener(
        'click',
        function () {

            const firstRow =
                productItems.querySelector(
                    '.production-item-row'
                );

            if (!firstRow) {
                return;
            }


            const newRow =
                firstRow.cloneNode(true);


            // Remove recipe information
            const recipeInformation =
                newRow.querySelector(
                    '.recipe-information'
                );

            if (recipeInformation) {
                recipeInformation.remove();
            }


            // Clear all input values
            newRow
                .querySelectorAll('input')
                .forEach(function (input) {

                    input.value = '';

                });


            // Reset product selection
            const select =
                newRow.querySelector(
                    'select'
                );

            if (select) {
                select.value = '';
            }


            productItems.appendChild(newRow);

        }
    );


    // --------------------------------------------------
    // Remove a Production Item
    // --------------------------------------------------

    productItems.addEventListener(
        'click',
        function (event) {

            const removeButton =
                event.target.closest(
                    '.remove-product'
                );


            if (!removeButton) {
                return;
            }


            const rows =
                productItems.querySelectorAll(
                    '.production-item-row'
                );


            // Keep at least one row
            if (rows.length === 1) {

                rows[0]
                    .querySelectorAll('input')
                    .forEach(function (input) {

                        input.value = '';

                    });


                const select =
                    rows[0].querySelector(
                        'select'
                    );


                if (select) {
                    select.value = '';
                }


                const recipeInformation =
                    rows[0].querySelector(
                        '.recipe-information'
                    );


                if (recipeInformation) {
                    recipeInformation.remove();
                }


                return;
            }


            removeButton
                .closest(
                    '.production-item-row'
                )
                .remove();

        }
    );

});