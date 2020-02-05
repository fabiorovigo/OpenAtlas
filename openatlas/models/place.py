from __future__ import annotations  # Needed for Python 4.0 type annotations

from typing import Any, Dict, List, Optional

from openatlas.models.entity import Entity
from openatlas.models.gis import Gis


def get_structure(object_: Optional[Entity] = None,
                  super_: Optional[Entity] = None,
                  mode: Optional[str] = None) -> Dict[str, Any]:
    super_id = None
    place = None
    feature = None
    stratigraphic_unit = None
    siblings: List[Entity] = []

    if super_:
        super_id = super_.id
        if super_.system_type == 'stratigraphic unit':
            feature = super_.get_linked_entity_safe('P46', inverse=True)
            place = feature.get_linked_entity_safe('P46', inverse=True)
        elif super_.system_type == 'feature':
            place = super_.get_linked_entity_safe('P46', inverse=True)
        elif super_.system_type == 'place':
            place = super_
        siblings = super_.get_linked_entities('P46')
    elif not object_:
        pass
    elif object_.system_type in ['find', 'human remains']:
        stratigraphic_unit = object_.get_linked_entity_safe('P46', inverse=True)
        super_id = stratigraphic_unit.id
        feature = stratigraphic_unit.get_linked_entity_safe('P46', inverse=True)
        place = feature.get_linked_entity_safe('P46', inverse=True)
        siblings = stratigraphic_unit.get_linked_entities('P46')  # Add finds of same stratigraphic
    elif object_.system_type == 'stratigraphic unit':
        feature = object_.get_linked_entity_safe('P46', inverse=True)
        super_id = feature.id
        place = feature.get_linked_entity_safe('P46', inverse=True)
    elif object_.system_type == 'feature':
        place = object_.get_linked_entity_safe('P46', inverse=True)
        super_id = place.id
    subunits = None
    if object_ and mode == 'view':
        subunits = object_.get_linked_entities('P46', nodes=True)
    return {'place': place,
            'feature': feature,
            'gis_data': Gis.get_all([object_] if object_ else None, super_id, subunits, siblings),
            'stratigraphic_unit': stratigraphic_unit,
            'super_id': super_id,
            'subunits': subunits,
            'siblings': siblings}
