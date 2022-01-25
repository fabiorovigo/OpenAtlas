from typing import Any, Tuple, Union

from flask import g

from openatlas.api.v03.resources.error import WrongOperatorError
from openatlas.api.v03.resources.search_validation import \
    check_if_date, check_if_date_search
from openatlas.api.v03.resources.util import \
    flatten_list_and_remove_duplicates, get_linked_entities_id_api, get_links
from openatlas.models.entity import Entity
from openatlas.models.type import Type


def search(
        entities: list[Entity],
        parser: list[dict[str, Any]]) -> list[Entity]:
    parameter = [get_search_parameter(p) for p in parser]
    return [e for e in entities if iterate_through_entities(e, parameter)]


def get_sub_ids(id_: int, subs: list[Any]) -> list[Any]:
    new_subs = Type.get_all_sub_ids(g.types[id_])
    subs.extend(new_subs)
    for sub in new_subs:
        get_sub_ids(sub, subs)
    return subs


def iterate_through_entities(
        entity: Entity,
        parameter: list[dict[str, Any]]) -> bool:
    return bool([p for p in parameter if search_result(entity, p)])


def search_result(entity: Entity, parameter: dict[str, Any]) -> bool:
    return bool(search_entity(
        entity_values=value_to_be_searched(entity, parameter['category']),
        operator_=parameter['operator'],
        search_values=parameter['search_values'],
        logical_operator=parameter['logical_operator'],
        is_comparable=parameter['is_date']))


def get_search_parameter(parser: dict[str, Any]) -> dict[str, Any]:
    parameter = {}
    for category, values in parser.items():
        for i in values:
            parameter.update({
                "search_values": get_search_values(category, i),
                "logical_operator": i['logicalOperator']
                    if 'logicalOperator' in i else 'or',
                "operator": 'equal'
                    if category == "valueTypeID" else i['operator'],
                "category": category,
                "is_date": check_if_date_search(category)})
    return parameter


def get_search_values(
        category: str,
        parameter: dict[str, Any]) -> list[Union[str, int]]:
    values = [value.lower() if isinstance(value, str) else value
              for value in parameter["values"]]
    if category in ["typeIDWithSubs"]:
        values += flatten_list_and_remove_duplicates(
            [get_sub_ids(value, []) for value in values])
    if category in ["relationToID"]:
        return flatten_list_and_remove_duplicates(
            [get_linked_entities_id_api(value) for value in values])
    if category in ["valueTypeID"]:
        return flatten_list_and_remove_duplicates(
            [search_for_value(value, parameter) for value in values])
    return values


def search_for_value(
        values: Tuple[int, float],
        parameter: dict[str, Any]) -> list[int]:
    links = get_links(values[0])
    ids = []
    for link_ in links:
        if link_.description and search_entity(
                entity_values=[float(link_.description)]
                    if parameter['operator']
                       in ['equal', 'notEqual'] else float(link_.description),
                operator_=parameter['operator'],
                search_values=[values[1]],
                logical_operator=parameter['logicalOperator'],
                is_comparable=True):
            ids.append(link_.domain.id)
    return ids


def search_entity(
        entity_values: Any,
        operator_: str,
        search_values: list[Any],
        logical_operator: str,
        is_comparable: bool) -> bool:
    if not entity_values and (operator_ == 'like' or is_comparable):
        return False
    if operator_ == 'equal':
        if logical_operator == 'or':
            return bool(any(item in entity_values for item in search_values))
        if logical_operator == 'and':
            return bool(all(item in entity_values for item in search_values))
    if operator_ == 'notEqual':
        if logical_operator == 'or':
            return bool(
                not any(item in entity_values for item in search_values))
        if logical_operator == 'and':
            return bool(
                not all(item in entity_values for item in search_values))
    if operator_ == 'like':
        if logical_operator == 'or':
            return bool(any(item in value for item in search_values
                            for value in entity_values))
        if logical_operator == 'and':
            return bool(all(item in ' '.join(entity_values)
                            for item in search_values ))
    if operator_ == 'greaterThan' and is_comparable:
        if logical_operator == 'or':
            return bool(any(item < entity_values for item in search_values))
        if logical_operator == 'and':
            return bool(all(item < entity_values for item in search_values))
    if operator_ == 'greaterThanEqual' and is_comparable:
        if logical_operator == 'or':
            return bool(any(item <= entity_values for item in search_values))
        if logical_operator == 'and':
            return bool(all(item <= entity_values for item in search_values))
    if operator_ == 'lesserThan' and is_comparable:
        if logical_operator == 'or':
            return bool(any(item > entity_values for item in search_values))
        if logical_operator == 'and':
            return bool(all(item > entity_values for item in search_values))
    if operator_ == 'lesserThanEqual' and is_comparable:
        if logical_operator == 'or':
            return bool(any(item >= entity_values for item in search_values))
        if logical_operator == 'and':
            return bool(all(item >= entity_values for item in search_values))
    raise WrongOperatorError


def value_to_be_searched(entity: Entity, key: str) -> Any:
    if key in ["entityID", "relationToID", "valueTypeID"]:
        return [entity.id]
    if key == "entityName":
        return [entity.name.lower()]
    if key == "entityDescription" and entity.description:
        return [entity.description.lower()]
    if key == "entityAliases":
        return list(value.lower() for value in entity.aliases.values())
    if key == "entityCidocClass":
        return [entity.cidoc_class.code.lower()]
    if key == "entitySystemClass":
        return [entity.class_.name.lower()]
    if key == "typeName":
        return [node.name.lower() for node in entity.types]
    if key in ["typeID", "typeIDWithSubs"]:
        return [node.id for node in entity.types]
    if key == "beginFrom":
        return check_if_date(str(entity.begin_from))
    if key == "beginTo":
        return check_if_date(str(entity.begin_to))
    if key == "endFrom":
        return check_if_date(str(entity.end_from))
    if key == "endTo":
        return check_if_date(str(entity.end_to))
    return []
