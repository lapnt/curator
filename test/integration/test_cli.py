import elasticsearch
import curator
import os
import json
import string, random, tempfile
import click
from click import testing as clicktest
from mock import patch, Mock

from . import CuratorTestCase
from . import testvars as testvars

import logging
logger = logging.getLogger(__name__)

host, port = os.environ.get('TEST_ES_SERVER', 'localhost:9200').split(':')
port = int(port) if port else 9200

class TestCLIMethods(CuratorTestCase):
    def test_bad_client_config(self):
        self.create_indices(10)
        self.write_config(
            self.args['configfile'],
            testvars.bad_client_config.format(host, port)
        )
        self.write_config(self.args['actionfile'],
            testvars.disabled_proto.format('close', 'delete_indices'))
        test = clicktest.CliRunner()
        result = test.invoke(
                    curator.cli,
                    [
                        '--config', self.args['configfile'],
                        '--dry-run',
                        self.args['actionfile']

                    ],
                    )
        self.assertEqual(-1, result.exit_code)
    def test_no_config(self):
        self.create_indices(10)
        self.write_config(
            self.args['configfile'],
            ' \n'
        )
        self.write_config(self.args['actionfile'],
            testvars.disabled_proto.format('close', 'delete_indices'))
        test = clicktest.CliRunner()
        result = test.invoke(
                    curator.cli,
                    [
                        '--config', self.args['configfile'],
                        '--dry-run',
                        self.args['actionfile']

                    ],
                    )
        self.assertEqual(0, result.exit_code)

    def test_no_logging_config(self):
        self.create_indices(10)
        self.write_config(
            self.args['configfile'],
            testvars.no_logging_config.format(host, port)
        )
        self.write_config(self.args['actionfile'],
            testvars.disabled_proto.format('close', 'delete_indices'))
        test = clicktest.CliRunner()
        result = test.invoke(
                    curator.cli,
                    [
                        '--config', self.args['configfile'],
                        '--dry-run',
                        self.args['actionfile']

                    ],
                    )
        self.assertEqual(0, result.exit_code)
    def test_invalid_action(self):
        self.write_config(
            self.args['configfile'], testvars.client_config.format(host, port))
        self.write_config(self.args['actionfile'],
            testvars.optionless_proto.format('invalid_action'))
        test = clicktest.CliRunner()
        result = test.invoke(
                    curator.cli,
                    [
                        '--config', self.args['configfile'],
                        self.args['actionfile']
                    ],
                    )
        self.assertEqual(-1, result.exit_code)
    def test_action_is_None(self):
        self.write_config(
            self.args['configfile'], testvars.client_config.format(host, port))
        self.write_config(self.args['actionfile'],
            testvars.optionless_proto.format(' '))
        test = clicktest.CliRunner()
        result = test.invoke(
                    curator.cli,
                    [
                        '--config', self.args['configfile'],
                        self.args['actionfile']
                    ],
                    )
        self.assertEqual(
            type(curator.ConfigurationError()), type(result.exception))
    def test_no_action(self):
        self.write_config(
            self.args['configfile'], testvars.client_config.format(host, port))
        self.write_config(self.args['actionfile'],
            testvars.actionless_proto)
        test = clicktest.CliRunner()
        result = test.invoke(
                    curator.cli,
                    [
                        '--config', self.args['configfile'],
                        self.args['actionfile']
                    ],
                    )
        self.assertEqual(
            type(curator.ConfigurationError()), type(result.exception))
    def test_dry_run(self):
        self.create_indices(10)
        self.write_config(
            self.args['configfile'], testvars.client_config.format(host, port))
        self.write_config(self.args['actionfile'],
            testvars.delete_proto.format(
                'age', 'name', 'older', '\'%Y.%m.%d\'', 'days', 5, ' ', ' ', ' '
            )
        )
        test = clicktest.CliRunner()
        result = test.invoke(
                    curator.cli,
                    [
                        '--config', self.args['configfile'],
                        '--dry-run',
                        self.args['actionfile']

                    ],
                    )
        self.assertEquals(10, len(curator.get_indices(self.client)))
    def test_action_disabled(self):
        self.create_indices(10)
        self.write_config(
            self.args['configfile'], testvars.client_config.format(host, port))
        self.write_config(self.args['actionfile'],
            testvars.disabled_proto.format('close', 'delete_indices'))
        test = clicktest.CliRunner()
        result = test.invoke(
                    curator.cli,
                    [
                        '--config', self.args['configfile'],
                        self.args['actionfile']
                    ],
                    )
        self.assertEquals(0, len(curator.get_indices(self.client)))
        self.assertEqual(0, result.exit_code)
    # I'll have to think up another way to create an exception.
    # The exception that using "alias" created, a missing argument,
    # is caught too early for this to actually run the test now :/
    #
    # def test_continue_if_exception(self):
    #     self.create_indices(10)
    #     self.write_config(
    #         self.args['configfile'], testvars.client_config.format(host, port))
    #     self.write_config(self.args['actionfile'],
    #         testvars.continue_proto.format(
    #             'alias', True, 'delete_indices', False
    #         )
    #     )
    #     test = clicktest.CliRunner()
    #     result = test.invoke(
    #                 curator.cli,
    #                 [
    #                     '--config', self.args['configfile'],
    #                     self.args['actionfile']
    #                 ],
    #                 )
    #     self.assertEquals(0, len(curator.get_indices(self.client)))
    #     self.assertEquals(type(curator.NoIndices()), type(result.exception))
    #     self.assertEqual(0, result.exit_code)
    def test_continue_if_exception_False(self):
        self.create_indices(10)
        self.write_config(
            self.args['configfile'], testvars.client_config.format(host, port))
        self.write_config(self.args['actionfile'],
            testvars.continue_proto.format(
                'close', False, 'delete_indices', False
            )
        )
        test = clicktest.CliRunner()
        result = test.invoke(
                    curator.cli,
                    [
                        '--config', self.args['configfile'],
                        self.args['actionfile']
                    ],
                    )
        self.assertEquals(10, len(curator.get_indices(self.client)))
        self.assertEqual(1, result.exit_code)
    def test_no_options_in_action(self):
        self.create_indices(10)
        self.write_config(
            self.args['configfile'], testvars.client_config.format(host, port))
        self.write_config(self.args['actionfile'],
            testvars.no_options_proto.format('delete_indices'))
        test = clicktest.CliRunner()
        result = test.invoke(
                    curator.cli,
                    [
                        '--config', self.args['configfile'],
                        '--dry-run',
                        self.args['actionfile']

                    ],
                    )
        self.assertEqual(0, result.exit_code)
