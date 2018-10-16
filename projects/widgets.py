from django.contrib.gis.forms import Widget
from django.forms import FileInput


class MapboxWidget(Widget):
    template_name = "mapbox_widget.html"

    class Media:
        css = {
            "all": (
                "https://api.tiles.mapbox.com/mapbox-gl-js/v0.43.0/mapbox-gl.css",
                "https://api.mapbox.com/mapbox-gl-js/plugins/mapbox-gl-draw/v1.0.0/mapbox-gl-draw.css",
            )
        }
        js = (
            "https://api.tiles.mapbox.com/mapbox-gl-js/v0.43.0/mapbox-gl.js",
            "https://cdn.jsdelivr.net/npm/@turf/turf@5/turf.min.js",
            "https://api.mapbox.com/mapbox-gl-js/plugins/mapbox-gl-draw/v1.0.0/mapbox-gl-draw.js",
        )

    def format_value(self, value):
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return value.geojson


class ImageWidget(FileInput):
    template_name = "image_widget.html"

    @staticmethod
    def get_delete_input_name(name):
        return "id_{}_delete".format(name)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        try:
            url = value.url
        # catch empty image field and None
        except (AttributeError, ValueError):
            url = None
        context["widget"].update(
            {"url": url, "delete_input_name": self.get_delete_input_name(name)}
        )

        return context

    def value_from_datadict(self, data, files, name):
        if data.get(self.get_delete_input_name(name), False):
            return False

        upload = super().value_from_datadict(data, files, name)
        return upload or None
