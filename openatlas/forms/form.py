from __future__ import annotations  # Needed for Python 4.0 type annotations

from typing import Optional

from flask import g, render_template
from flask_babel import lazy_gettext as _
from flask_wtf import FlaskForm
from wtforms import (
    HiddenField, SelectMultipleField, StringField, SubmitField, widgets)
from wtforms.validators import InputRequired

from openatlas import app
from openatlas.forms import base_manager, manager
from openatlas.forms.field import TableField, TreeField
from openatlas.models.entity import Entity
from openatlas.models.link import Link
from openatlas.models.type import Type
from openatlas.util.table import Table
from openatlas.util.util import get_base_table_data, uc_first


def get_manager(
        class_name: Optional[str] = None,
        entity: Optional[Entity] = None,
        origin: Optional[Entity] = None,
        link_: Optional[Link] = None) -> base_manager.BaseManager:
    name = entity.class_.name if entity and not class_name else class_name
    manager_name = ''.join(i.capitalize() for i in name.split('_'))
    manager_instance = getattr(manager, f'{manager_name}Manager')(
        class_=g.classes['type' if name.startswith('hierarchy') else name],
        entity=entity,
        origin=origin,
        link_=link_)
    if not entity and not link_:
        manager_instance.populate_insert()
    return manager_instance


def get_add_reference_form(class_: str) -> FlaskForm:
    class Form(FlaskForm):
        pass

    setattr(Form, class_, TableField(_(class_), [InputRequired()]))
    setattr(Form, 'page', StringField(_('page')))
    setattr(Form, 'save', SubmitField(uc_first(_('insert'))))
    return Form()


def get_table_form(class_: str, linked_entities: list[Entity]) -> str:
    """ Returns a form with a list of entities with checkboxes."""
    if class_ == 'place':
        entities = Entity.get_by_class('place', types=True, aliases=True)
    elif class_ == 'artifact':
        entities = Entity.get_by_class(
            ['artifact', 'human_remains'],
            types=True)
    else:
        entities = Entity.get_by_view(class_, types=True, aliases=True)
    linked_ids = [entity.id for entity in linked_entities]
    table = Table([''] + g.table_headers[class_], order=[[1, 'asc']])
    for entity in entities:
        if entity.id in linked_ids:
            continue  # Don't show already linked entries
        input_ = f"""
            <input
                id="selection-{entity.id}"
                name="values"
                type="checkbox"
                value="{entity.id}">"""
        table.rows.append(
            [input_] + get_base_table_data(entity, show_links=False))
    if not table.rows:
        return uc_first(_('no entries'))
    return render_template(
        'forms/form_table.html',
        table=table.display(class_))


def get_move_form(type_: Type) -> FlaskForm:
    class Form(FlaskForm):
        is_type_form = HiddenField()
        checkbox_values = HiddenField()
        selection = SelectMultipleField(
            '',
            [InputRequired()],
            coerce=int,
            option_widget=widgets.CheckboxInput(),
            widget=widgets.ListWidget(prefix_label=False))
        save = SubmitField(uc_first(_('move entities')))

    root = g.types[type_.root[0]]
    setattr(Form, str(root.id), TreeField(str(root.id)))
    choices = []
    if root.class_.name == 'administrative_unit':
        for entity in type_.get_linked_entities('P89', True):
            place = entity.get_linked_entity('P53', True)
            if place:
                choices.append((entity.id, place.name))
    elif root.name in app.config['PROPERTY_TYPES']:
        for row in Link.get_links_by_type(type_):
            domain = Entity.get_by_id(row['domain_id'])
            range_ = Entity.get_by_id(row['range_id'])
            choices.append((row['id'], domain.name + ' - ' + range_.name))
    else:
        for entity in type_.get_linked_entities('P2', True):
            choices.append((entity.id, entity.name))
    form = Form(obj=type_)
    form.selection.choices = choices
    return form
