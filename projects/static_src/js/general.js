$(() => {
  $('#application-sidebar-affix').affix({
    offset: {
      top: function () {
        return (this.top = $('#new-application').offset().top - 15)
      },
      bottom: function () {
        return (this.bottom = $('.site-footer').outerHeight(true) + 100)
      }
    }
  });

  $('[data-toggle="tooltip"]').tooltip();
});
