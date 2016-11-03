# coding=utf8

import l20n.format.ast as FTL


def get_entity(body, ident):
    """Get entity called `ident` from `body`."""
    for entity in body:
        if entity.id.name == ident:
            return entity


def merge(reference, localization, transforms, in_changeset):
    """Transform legacy translations into FTL.

    Use the `reference` FTL AST as a template.  For each en-US string in the
    reference, first check if it's in the currently processed changeset with
    `in_changeset`; then check for an existing translation in the current FTL
    `localization` or for a migration specification in `transforms`.
    """

    def merge_body(body):
        return [
            entry
            for entry in map(merge_entry, body)
            if entry is not None
        ]

    def merge_entry(entry):
        if isinstance(entry, FTL.Comment):
            return entry

        if isinstance(entry, FTL.Section):
            return FTL.Section(
                key=entry.key,
                body=merge_body(entry.body),
                comment=entry.comment
            )

        ident = entry.id.name

        # If the message is present in the existing localization, we add it to
        # the resulting resource.  This ensures consecutive merges don't remove
        # translations but rather create supersets of them.
        existing = get_entity(localization.body, ident)
        if existing is not None:
            return existing

        # If the message doesn't exist if the localization yet, make sure it's
        # supposed to be added as part of this merger.
        if not in_changeset(ident):
            return None

        transform = get_entity(transforms, ident)
        if transform is not None:
            if transform.comment is None:
                transform.comment = entry.comment
            return transform

    body = merge_body(reference.body)
    return FTL.Resource(body, reference.comment)