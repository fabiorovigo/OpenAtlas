def get_test_geometric_entity(params):
    return {
        'type': 'FeatureCollection',
        'features': [{
            'type': 'Feature',
            'geometry': {'coordinates': [9, 17], 'type': 'Point'},
            'properties': {
                'id': 1,
                'name': '',
                'description': '',
                'objectId': params["shire_id"],
                'objectDescription': 'The Shire was the homeland of the hobbits.',
                'objectName': 'Shire',
                'objectType': None,
                'shapeType': 'centerpoint'}}]}
