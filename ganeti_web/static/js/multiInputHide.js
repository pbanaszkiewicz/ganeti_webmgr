function multi_input(selector) {
    var $selector = $(selector);
    var $add = $('<a class="icon add multi"></a>');
    var $del = $('<a class="icon delete multi"></a>');

    var cursor;
    $add.click(function(e) {
        e.preventDefault();
        if (typeof(cursor) === 'undefined') {
            cursor = $(this).parents("tr").next();
        } else {
            cursor = cursor.next();
        }
        cursor.show();
    });

    // hide all but the first inputs for group of multi_inputs
    $selector.not('.first').parents("tr").hide();

    $('.first', $selector).each(function(index) {
        $(this).parent().append($add);
        $(this).parent().append($del);
    });
}
