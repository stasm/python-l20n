# coding=utf8

import unittest

import l20n.format.ast as FTL
from compare_locales.parser import PropertiesParser
from util import parse, ftl_message_to_json

from operations import COPY, REPLACE, VARIANTS


# Mock SOURCE using the collection parsed in setUp.
def SOURCE(collection, key):
    return collection.get(key, None).get_val()


# Create a PLURALS transform for en-US.
def PLURALS(source, selector, foreach):
    return VARIANTS(source, selector, ('one', 'other'), foreach)


class TestPlural(unittest.TestCase):
    def setUp(self):
        self.strings = parse(PropertiesParser, '''
            deleteAll=Delete this download?;Delete all downloads?
        ''')

    def test_plural(self):
        msg = FTL.Entity(
            FTL.Identifier('delete-all'),
            value=PLURALS(
                SOURCE(self.strings, 'deleteAll'),
                FTL.ExternalArgument('num'),
                lambda var: COPY(var)
            )
        )

        self.assertEqual(
            msg.toJSON(),
            ftl_message_to_json('''
                delete-all = { $num ->
                    [one] Delete this download?
                   *[other] Delete all downloads?
                }
            ''')
        )


class TestPluralReplace(unittest.TestCase):
    def setUp(self):
        self.strings = parse(PropertiesParser, '''
            deleteAll=Delete this download?;Delete #1 downloads?
        ''')

    def test_plural_replace(self):
        msg = FTL.Entity(
            FTL.Identifier('delete-all'),
            value=PLURALS(
                SOURCE(self.strings, 'deleteAll'),
                FTL.ExternalArgument('num'),
                lambda var: REPLACE(
                    var,
                    {'#1': [FTL.ExternalArgument('num')]}
                )
            )
        )

        self.assertEqual(
            msg.toJSON(),
            ftl_message_to_json('''
                delete-all = { $num ->
                    [one] Delete this download?
                   *[other] Delete { $num } downloads?
                }
            ''')
        )


if __name__ == '__main__':
    unittest.main()