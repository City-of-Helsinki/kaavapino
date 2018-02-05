from django.contrib.gis import forms


class MapboxWidget(forms.Widget):
    template_name = 'mapbox_widget.html'

    class Media:
        css = {
            'all':
                (
                    'https://api.tiles.mapbox.com/mapbox-gl-js/v0.43.0/mapbox-gl.css',
                    'https://api.mapbox.com/mapbox-gl-js/plugins/mapbox-gl-draw/v1.0.0/mapbox-gl-draw.css',
                )
        }
        js = (
            'https://api.tiles.mapbox.com/mapbox-gl-js/v0.43.0/mapbox-gl.js',
            'https://cdn.jsdelivr.net/npm/@turf/turf@5/turf.min.js',
            'https://api.mapbox.com/mapbox-gl-js/plugins/mapbox-gl-draw/v1.0.0/mapbox-gl-draw.js',
        )

    def format_value(self, value):
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return value.geojson
