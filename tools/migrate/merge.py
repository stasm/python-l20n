# coding=utf8

import os
import codecs
import logging

import l20n.format.ast as FTL
from l20n.format.parser import FTLParser
from l20n.format.serializer import FTLSerializer
from compare_locales.parser import getParser

from cldr import get_plural_categories
from operations import VARIANTS


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

    def merge_entry(entry):
        ident = entry.id.name

        if not in_changeset(ident):
            return None

        existing = get_entity(localization.body, ident)
        if existing is not None:
            return existing

        transform = get_entity(transforms, ident)
        if transform is not None:
            return transform

    body = [
        entry for entry in map(merge_entry, reference.body)
        if entry is not None
    ]

    return FTL.Resource(body, reference.comment)


class MergeContext(object):
    """Stateful context for merging translation resources.

    `MergeContext` must be configured with the target language and the
    directory locations of the input data.

    The transformation takes four types of input data:

        - The en-US FTL reference files which will be used as templates for
          message order, comments and sections.

        - The current FTL files for the given language.

        - The legacy (DTD, properties) translation files for the given
          language.  The translations from these files will be transformed
          into FTL and merged into the existing FTL files for this language.

        - A list of `FTL.Entity` objects whose some nodes are special operation
          nodes: COPY, REPLACE, PLURALS, CONCAT, INTERPOLATE.
    """

    def __init__(self, lang, reference_dir, localization_dir):
        self.ftl_parser = FTLParser()
        self.ftl_serializer = FTLSerializer()

        # An iterable of plural category names relevant to the context's
        # language.  E.g. ('one', 'other') for English.
        self.plural_categories = get_plural_categories(lang)

        # Paths to directories with input data, relative to CWD.
        self.reference_dir = reference_dir
        self.localization_dir = localization_dir

        # Parsed input resources stored by resource path.
        self.reference_resources = {}
        self.current_resources = {}
        self.legacy_resources = {}

        # An iterable of `FTL.Entity` object whose some nodes can be the
        # transform operations: COPY, REPLACE, PLURALS, CONCAT, INTERPOLATE.
        self.transforms = {}

        # Keep track of the current FTL message when building the transforms
        # using MESSAGE.  Each subsequent use of SOURCE will add the source
        # translation to the set of dependencies for this message.
        self.current_message = None
        self.dependencies = {}

    def read_ftl_resource(self, path):
        f = codecs.open(path, 'r', 'utf8')
        try:
            contents = f.read()
        except UnicodeDecodeError, err:
            logger = logging.getLogger('migrate')
            logger.error(u'Error reading file {}: {}'.format(path, str(err)))
        f.close()

        ast, errors = self.ftl_parser.parse(contents)

        if len(errors):
            logger = logging.getLogger('migrate')
            for err in errors:
                logger.error(u'Syntax error in {}: {}'.format(path, str(err)))

        return ast

    def add_reference(self, path):
        """Add an FTL AST to this context's reference resources."""
        fullpath = os.path.join(self.reference_dir, path)
        self.reference_resources[path] = self.read_ftl_resource(fullpath)

    def add_current(self, path):
        """Add an FTL AST to this context's current localization resources."""
        fullpath = os.path.join(self.localization_dir, path)
        self.current_resources[path] = self.read_ftl_resource(fullpath)

    def add_legacy(self, path):
        """Add a dict to this context's legacy localization resources."""
        fullpath = os.path.join(self.localization_dir, path)
        parser = getParser(fullpath)
        parser.readFile(fullpath)
        # Transform the parsed result which is an iterator into a dict.
        collection = {ent.get_key(): ent for ent in parser}
        self.legacy_resources[path] = collection

    def add_transforms(self, transforms):
        """Define transforms for resource paths.

        Each transform is a (path, Node) tuple.
        """
        for path, node in transforms:
            self.current_message = None
            path_transforms = self.transforms.setdefault(path, [])
            path_transforms.append(node)

    def create_message(self):
        """Create a MESSAGE partial which returns another partial.

        Use the `MESSAGE` partial instead of `FTL.Entity`.  It will set the
        context's internal state such that each subsequent use of SOURCE will
        add the source translations as dependencies of the current message.

        The `MESSAGE` partial returns a partial itself.  Call it to specify the
        `value` and/or the `traits` transforms.

            ctx.add_transforms([
                MESSAGE('aboutDownloads.ftl', 'title')(
                    value=COPY(
                        SOURCE(
                            'aboutDownloads.dtd',
                            'aboutDownloads.title'
                        )
                    )
                ),
            ])
        """
        def message(path, key):
            # Set the context's internal state for SOURCE to work correctly.
            self.current_message = (path, key)
            self.dependencies[self.current_message] = set()

            def partial(value=None, traits=None):
                # Return `path` for `add_transforms`.
                return path, FTL.Entity(
                    FTL.Identifier(key), value, traits
                )
            return partial
        return message

    def create_source(self):
        """Create a SOURCE partial for use with other operations."""
        def source(path, key):
            # Set this source as a dependency for the current message.
            current_dependencies = self.dependencies[self.current_message]
            current_dependencies.add((path, key))

            entity = self.legacy_resources[path].get(key, None)
            if entity is not None:
                return entity.get_val()
        return source

    def create_plurals(self):
        """Create a PLURALS partial for use with other operations."""
        def plurals(source, selector, foreach):
            # Use this context's plural categories as variant keys.
            return VARIANTS(source, selector, self.plural_categories, foreach)
        return plurals

    def merge(self, changeset=None):
        """Transform and merge context's input data.

        The input data must be configured earlier using the `add_*` methods.
        if given, `changeset` must be a set of (path, key) tuples describing
        which legacy translations are to be merged.
        """

        if changeset is None:
            # Merge all known legacy translations.
            changeset = {
                (path, key)
                for path, strings in self.legacy_resources.iteritems()
                for key in strings.iterkeys()
            }

        result = {}

        for path, reference in self.reference_resources.iteritems():

            def in_changeset(ident):
                """Check if entity should be merged.

                If at least one dependency of the entity is in the current
                changeset, merge it.
                """
                message_deps = self.dependencies.get((path, ident), set())
                # Take the intersection of dependencies and the changeset.
                return message_deps & changeset

            current = self.current_resources.get(path, FTL.Resource())
            transforms = self.transforms.get(path, [])

            merged = merge(reference, current, transforms, in_changeset)
            result[path] = self.ftl_serializer.serialize(merged.toJSON())

        return result