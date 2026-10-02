document.addEventListener('DOMContentLoaded', function () {

    const productSelect =
        document.getElementById('id_product');

    const quantityInput =
        document.getElementById('id_quantity');

    const unitPriceDisplay =
        document.getElementById('unit-price');

    const totalPriceDisplay =
        document.getElementById('total-price');

    const availableStockDisplay =
        document.getElementById('available-stock');

    const saleForm =
        quantityInput.closest('form');


    // ---------------------------------------------------------
    // STOCK MESSAGE
    // ---------------------------------------------------------

    const stockMessage =
        document.createElement('div');

    stockMessage.className =
        'sale-stock-message';

    quantityInput.parentNode.appendChild(
        stockMessage
    );


    function calculateTotal() {

        const selectedOption =
            productSelect.options[
                productSelect.selectedIndex
            ];


        // -----------------------------------------------------
        // NO PRODUCT SELECTED
        // -----------------------------------------------------

        if (
            !selectedOption ||
            !selectedOption.value
        ) {

            unitPriceDisplay.textContent =
                '0.00 ETB';

            totalPriceDisplay.textContent =
                '0.00 ETB';

            availableStockDisplay.textContent =
                '0';

            quantityInput.removeAttribute('max');

            stockMessage.textContent = '';

            stockMessage.classList.remove(
                'show'
            );

            return;
        }


        // -----------------------------------------------------
        // PRODUCT INFORMATION
        // -----------------------------------------------------

        const unitPrice =
            parseFloat(
                selectedOption.getAttribute(
                    'data-price'
                ) || '0'
            );


        const availableStock =
            parseFloat(
                selectedOption.getAttribute(
                    'data-stock'
                ) || '0'
            );


        const wholeStock =
            Math.floor(availableStock);


        const quantity =
            parseFloat(
                quantityInput.value || '0'
            );


        // -----------------------------------------------------
        // SET MAXIMUM
        // -----------------------------------------------------

        quantityInput.max =
            wholeStock;


        // -----------------------------------------------------
        // DISPLAY AVAILABLE STOCK
        // -----------------------------------------------------

        availableStockDisplay.textContent =
            wholeStock.toString();


        // -----------------------------------------------------
        // STOCK VALIDATION MESSAGE
        // -----------------------------------------------------

        if (wholeStock === 0) {

            stockMessage.textContent =
                'Unavailable: This product is currently out of stock.';

            stockMessage.classList.add(
                'show'
            );

        }

        else if (
            quantity > wholeStock
        ) {

            stockMessage.textContent =
                `Unavailable: Only ${wholeStock} units are available.`;

            stockMessage.classList.add(
                'show'
            );

        }

        else {

            stockMessage.textContent = '';

            stockMessage.classList.remove(
                'show'
            );
        }


        // -----------------------------------------------------
        // PRICE CALCULATION
        // -----------------------------------------------------

        unitPriceDisplay.textContent =
            unitPrice.toFixed(2) + ' ETB';


        const total =
            unitPrice * quantity;


        totalPriceDisplay.textContent =
            total.toFixed(2) + ' ETB';
    }


    // ---------------------------------------------------------
    // PRODUCT CHANGED
    // ---------------------------------------------------------

    productSelect.addEventListener(
        'change',
        function () {

            quantityInput.value = '';

            calculateTotal();
        }
    );


    // ---------------------------------------------------------
    // QUANTITY CHANGED
    // ---------------------------------------------------------

    quantityInput.addEventListener(
        'input',
        calculateTotal
    );


    // ---------------------------------------------------------
    // PREVENT INVALID SALE
    // ---------------------------------------------------------

    saleForm.addEventListener(
        'submit',
        function (event) {

            const selectedOption =
                productSelect.options[
                    productSelect.selectedIndex
                ];


            if (
                !selectedOption ||
                !selectedOption.value
            ) {
                return;
            }


            const availableStock =
                Math.floor(
                    parseFloat(
                        selectedOption.getAttribute(
                            'data-stock'
                        ) || '0'
                    )
                );


            const quantity =
                parseFloat(
                    quantityInput.value || '0'
                );


            if (
                availableStock === 0
            ) {

                event.preventDefault();

                stockMessage.textContent =
                    'Unavailable: This product is currently out of stock.';

                stockMessage.classList.add(
                    'show'
                );

                return;
            }


            if (
                quantity > availableStock
            ) {

                event.preventDefault();

                stockMessage.textContent =
                    `Unavailable: Only ${availableStock} units are available.`;

                stockMessage.classList.add(
                    'show'
                );

                quantityInput.focus();

                return;
            }
        }
    );


    // ---------------------------------------------------------
    // INITIAL CALCULATION
    // ---------------------------------------------------------

    calculateTotal();

});