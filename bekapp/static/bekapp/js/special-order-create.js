document.addEventListener('DOMContentLoaded', function () {

    const itemsContainer = document.getElementById(
        'special-order-items'
    );

    const addItemButton = document.getElementById(
        'add-special-order-item'
    );

    const grandTotalElement = document.getElementById(
        'special-order-grand-total'
    );


    if (
        !itemsContainer ||
        !addItemButton ||
        !grandTotalElement
    ) {
        return;
    }


    /* =========================================================
       UPDATE ONE PRODUCT ROW
    ========================================================= */

    function updateItemTotal(row) {

        const productSelect = row.querySelector(
            '.special-order-product'
        );

        const quantityInput = row.querySelector(
            '.special-order-quantity'
        );

        const priceInput = row.querySelector(
            '.special-order-price'
        );

        const totalInput = row.querySelector(
            '.special-order-total'
        );


        if (
            !productSelect ||
            !quantityInput ||
            !priceInput ||
            !totalInput
        ) {
            return;
        }


        const selectedOption =
            productSelect.options[
                productSelect.selectedIndex
            ];


        let price = 0;


        if (
            selectedOption &&
            selectedOption.dataset.price
        ) {
            price = parseFloat(
                selectedOption.dataset.price
            ) || 0;
        }


        const quantity =
            parseFloat(quantityInput.value) || 0;


        const total = price * quantity;


        priceInput.value = price.toFixed(2);

        totalInput.value = total.toFixed(2);
    }


    /* =========================================================
       UPDATE GRAND TOTAL
    ========================================================= */

    function updateGrandTotal() {

        let grandTotal = 0;


        const rows =
            itemsContainer.querySelectorAll(
                '.special-order-item-row'
            );


        rows.forEach(function (row) {

            const totalInput = row.querySelector(
                '.special-order-total'
            );


            if (totalInput) {

                grandTotal +=
                    parseFloat(totalInput.value) || 0;

            }

        });


        grandTotalElement.textContent =
            grandTotal.toFixed(2) + ' ETB';
    }


    /* =========================================================
       UPDATE ROW AND GRAND TOTAL
    ========================================================= */

    function updateRow(row) {

        updateItemTotal(row);

        updateGrandTotal();

    }


    /* =========================================================
       ATTACH EVENTS TO A PRODUCT ROW
    ========================================================= */

    function attachRowEvents(row) {

        const productSelect = row.querySelector(
            '.special-order-product'
        );

        const quantityInput = row.querySelector(
            '.special-order-quantity'
        );

        const removeButton = row.querySelector(
            '.special-order-remove-item'
        );


        /* PRODUCT CHANGE */

        if (productSelect) {

            productSelect.addEventListener(
                'change',
                function () {

                    updateRow(row);

                }
            );

        }


        /* QUANTITY CHANGE */

        if (quantityInput) {

            quantityInput.addEventListener(
                'input',
                function () {

                    updateRow(row);

                }
            );

        }


        /* REMOVE PRODUCT */

        if (removeButton) {

            removeButton.addEventListener(
                'click',
                function () {

                    const rows =
                        itemsContainer.querySelectorAll(
                            '.special-order-item-row'
                        );


                    /*
                     * Keep at least one row.
                     */

                    if (rows.length === 1) {

                        const productSelect =
                            row.querySelector(
                                '.special-order-product'
                            );

                        const quantityInput =
                            row.querySelector(
                                '.special-order-quantity'
                            );

                        const customization =
                            row.querySelector(
                                '.special-order-customization'
                            );


                        if (productSelect) {
                            productSelect.value = '';
                        }


                        if (quantityInput) {
                            quantityInput.value = '1';
                        }


                        if (customization) {
                            customization.value = '';
                        }


                        updateRow(row);

                        return;
                    }


                    row.remove();

                    updateGrandTotal();

                }
            );

        }

    }


    /* =========================================================
       FIRST ROW
    ========================================================= */

    const firstRow =
        itemsContainer.querySelector(
            '.special-order-item-row'
        );


    if (firstRow) {

        attachRowEvents(firstRow);

    }


    /* =========================================================
       ADD PRODUCT
    ========================================================= */

    addItemButton.addEventListener(
        'click',
        function () {

            const firstRow =
                itemsContainer.querySelector(
                    '.special-order-item-row'
                );


            if (!firstRow) {
                return;
            }


            const newRow =
                firstRow.cloneNode(true);


            /* RESET PRODUCT */

            const productSelect =
                newRow.querySelector(
                    '.special-order-product'
                );

            if (productSelect) {
                productSelect.value = '';
            }


            /* RESET QUANTITY */

            const quantityInput =
                newRow.querySelector(
                    '.special-order-quantity'
                );

            if (quantityInput) {
                quantityInput.value = '1';
            }


            /* RESET UNIT PRICE */

            const priceInput =
                newRow.querySelector(
                    '.special-order-price'
                );

            if (priceInput) {
                priceInput.value = '0.00';
            }


            /* RESET TOTAL */

            const totalInput =
                newRow.querySelector(
                    '.special-order-total'
                );

            if (totalInput) {
                totalInput.value = '0.00';
            }


            /* RESET CUSTOMIZATION */

            const customization =
                newRow.querySelector(
                    '.special-order-customization'
                );

            if (customization) {
                customization.value = '';
            }


            itemsContainer.appendChild(newRow);


            attachRowEvents(newRow);

            updateGrandTotal();

        }
    );


    /* =========================================================
       INITIAL TOTAL
    ========================================================= */

    updateGrandTotal();

});