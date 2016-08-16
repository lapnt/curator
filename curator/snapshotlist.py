from datetime import timedelta, datetime, date
import time
import re
import logging
from .defaults import settings
from .validators import SchemaCheck, filters
from .exceptions import *
from .utils import *


class SnapshotList(object):
    def __init__(self, client, repository=None):
        verify_client_object(client)
        if not repository:
            raise MissingArgument('No value for "repository" provided')
        if not repository_exists(client, repository):
            raise FailedExecution(
                'Unable to verify existence of repository '
                '{0}'.format(repository)
            )
        self.loggit = logging.getLogger('curator.snapshotlist')
        #: An Elasticsearch Client object.
        #: Also accessible as an instance variable.
        self.client = client
        #: An Elasticsearch repository.
        #: Also accessible as an instance variable.
        self.repository = repository
        #: Instance variable.
        #: Information extracted from snapshots, such as age, etc.
        #: Populated by internal method `__get_snapshots` at instance creation
        #: time. **Type:** ``dict()``
        self.snapshot_info = {}
        #: Instance variable.
        #: The running list of snapshots which will be used by an Action class.
        #: Populated by internal methods `__get_snapshots` at instance creation
        #: time. **Type:** ``list()``
        self.snapshots = []
        #: Instance variable.
        #: Raw data dump of all snapshots in the repository at instance creation
        #: time.  **Type:** ``list()`` of ``dict()`` data.
        self.__get_snapshots()


    def __actionable(self, snap):
        self.loggit.debug(
            'Snapshot {0} is actionable and remains in the list.'.format(snap))

    def __not_actionable(self, snap):
            self.loggit.debug(
                'Snapshot {0} is not actionable, removing from '
                'list.'.format(snap)
            )
            self.snapshots.remove(snap)

    def __excludify(self, condition, exclude, snap, msg=None):
        if condition == True:
            if exclude:
                text = "Removed from actionable list"
                self.__not_actionable(snap)
            else:
                text = "Remains in actionable list"
                self.__actionable(snap)
        else:
            if exclude:
                text = "Remains in actionable list"
                self.__actionable(snap)
            else:
                text = "Removed from actionable list"
                self.__not_actionable(snap)
        if msg:
            self.loggit.debug('{0}: {1}'.format(text, msg))

    def __get_snapshots(self):
        """
        Pull all snapshots into `snapshots` and populate
        `snapshot_info`
        """
        self.all_snapshots = get_snapshot_data(self.client, self.repository)
        for list_item in self.all_snapshots:
            if 'snapshot' in list_item.keys():
                self.snapshots.append(list_item['snapshot'])
                self.snapshot_info[list_item['snapshot']] = list_item
        self.empty_list_check()

    def __map_method(self, ft):
        methods = {
            'age': self.filter_by_age,
            'none': self.filter_none,
            'pattern': self.filter_by_regex,
            'state': self.filter_by_state,
        }
        return methods[ft]

    def empty_list_check(self):
        """Raise exception if `snapshots` is empty"""
        if not self.snapshots:
            raise NoSnapshots('snapshot_list object is empty.')

    def working_list(self):
        """
        Return the current value of `snapshots` as copy-by-value to prevent list
        stomping during iterations
        """
        # Copy by value, rather than reference to prevent list stomping during
        # iterations
        return self.snapshots[:]

    def _get_name_based_ages(self, timestring):
        """
        Add a snapshot age to `snapshot_info` based on the age as indicated
        by the snapshot name pattern, if it matches `timestring`.  This is
        stored at key ``age_by_name``.

        :arg timestring: An strftime pattern
        """
        # Check for empty list before proceeding here to prevent non-iterable
        # condition
        self.empty_list_check()
        ts = TimestringSearch(timestring)
        for snapshot in self.working_list():
            epoch = ts.get_epoch(snapshot)
            if epoch:
                self.snapshot_info[snapshot]['age_by_name'] = epoch
            else:
                self.snapshot_info[snapshot]['age_by_name'] = None

    def most_recent(self):
        """
        Return the most recent snapshot based on `start_time_in_millis`.
        """
        self.empty_list_check()
        most_recent_time = 0
        most_recent_snap = ''
        for snapshot in self.snapshots:
            snaptime = fix_epoch(
                self.snapshot_info[snapshot]['start_time_in_millis'])
            if snaptime > most_recent_time:
                most_recent_snap = snapshot
                most_recent_time = snaptime
        return most_recent_snap


    def filter_by_regex(self, kind=None, value=None, exclude=False):
        """
        Filter out indices not matching the pattern, or in the case of exclude,
        filter those matching the pattern.

        :arg kind: Can be one of: ``suffix``, ``prefix``, ``regex``, or
            ``timestring``. This option defines what kind of filter you will be
            building.
        :arg value: Depends on `kind`. It is the strftime string if `kind` is
            `timestring`. It's used to build the regular expression for other
            kinds.
        :arg exclude: If `exclude` is `True`, this filter will remove matching
            snapshots from `snapshots`. If `exclude` is `False`, then only
            matching snapshots will be kept in `snapshots`.
            Default is `False`
        """
        if kind not in [ 'regex', 'prefix', 'suffix', 'timestring' ]:
            raise ValueError('{0}: Invalid value for kind'.format(kind))

        # Stop here if None or empty value, but zero is okay
        if value == 0:
            pass
        elif not value:
            raise ValueError(
                '{0}: Invalid value for "value". '
                'Cannot be "None" type, empty, or False'
            )

        if kind == 'timestring':
            regex = settings.regex_map()[kind].format(get_date_regex(value))
        else:
            regex = settings.regex_map()[kind].format(value)

        self.empty_list_check()
        pattern = re.compile(regex)
        for snapshot in self.working_list():
            match = pattern.match(snapshot)
            self.loggit.debug('Filter by regex: Snapshot: {0}'.format(snapshot))
            if match:
                self.__excludify(True, exclude, snapshot)
            else:
                self.__excludify(False, exclude, snapshot)

    def filter_by_age(self, source='creation_date', direction=None,
        timestring=None, unit=None, unit_count=None, epoch=None, exclude=False
        ):
        """
        Remove snapshots from `snapshots` by relative age calculations.

        :arg source: Source of snapshot age. Can be 'name', or 'creation_date'.
        :arg direction: Time to filter, either ``older`` or ``younger``
        :arg timestring: An strftime string to match the datestamp in an
            snapshot name. Only used for snapshot filtering by ``name``.
        :arg unit: One of ``seconds``, ``minutes``, ``hours``, ``days``,
            ``weeks``, ``months``, or ``years``.
        :arg unit_count: The number of ``unit``s. ``unit_count`` * ``unit`` will
            be calculated out to the relative number of seconds.
        :arg epoch: An epoch timestamp used in conjunction with ``unit`` and
            ``unit_count`` to establish a point of reference for calculations.
            If not provided, the current time will be used.
        :arg exclude: If `exclude` is `True`, this filter will remove matching
            snapshots from `snapshots`. If `exclude` is `False`, then only
            matching snapshots will be kept in `snapshots`.
            Default is `False`
        """
        self.loggit.debug('Starting filter_by_age')
        # Get timestamp point of reference, PoR
        PoR = get_point_of_reference(unit, unit_count, epoch)
        self.loggit.debug('Point of Reference: {0}'.format(PoR))
        if not direction:
            raise MissingArgument('Must provide a value for "direction"')
        if direction not in ['older', 'younger']:
            raise ValueError(
                'Invalid value for "direction": {0}'.format(direction)
            )
        if source == 'name':
            keyfield = 'age_by_name'
            if not timestring:
                raise MissingArgument(
                    'source "name" requires the "timestamp" keyword argument'
                )
            self._get_name_based_ages(timestring)
        elif source == 'creation_date':
            keyfield = 'start_time_in_millis'
        else:
            raise ValueError(
                'Invalid source: {0}.  '
                'Must be "name", or "creation_date".'.format(source)
            )

        for snapshot in self.working_list():
            if not self.snapshot_info[snapshot][keyfield]:
                self.loggit.debug('Removing snapshot {0} for having no age')
                self.snapshots.remove(snapshot)
                continue
            msg = (
                'Snapshot "{0}" age ({1}), direction: "{2}", point of '
                'reference, ({3})'.format(
                    snapshot,
                    fix_epoch(self.snapshot_info[snapshot][keyfield]),
                    direction,
                    PoR
                )
            )
            # Because time adds to epoch, smaller numbers are actually older
            # timestamps.
            if direction == 'older':
                agetest = fix_epoch(self.snapshot_info[snapshot][keyfield]) < PoR
            else: # 'younger'
                agetest = fix_epoch(self.snapshot_info[snapshot][keyfield]) > PoR
            self.__excludify(agetest, exclude, snapshot, msg)

    def filter_by_state(self, state=None, exclude=False):
        """
        Filter out indices not matching ``state``, or in the case of exclude,
        filter those matching ``state``.

        :arg state: The snapshot state to filter for. Must be one of
            ``SUCCESS``, ``PARTIAL``, ``FAILED``, or ``IN_PROGRESS``.
        :arg exclude: If `exclude` is `True`, this filter will remove matching
            snapshots from `snapshots`. If `exclude` is `False`, then only
            matching snapshots will be kept in `snapshots`.
            Default is `False`
        """
        if state.upper() not in ['SUCCESS', 'PARTIAL', 'FAILED', 'IN_PROGRESS']:
            raise ValueError('{0}: Invalid value for state'.format(state))

        self.empty_list_check()
        for snapshot in self.working_list():
            self.loggit.debug('Filter by state: Snapshot: {0}'.format(snapshot))
            if self.snapshot_info[snapshot]['state'] == state:
                self.__excludify(True, exclude, snapshot)
            else:
                self.__excludify(False, exclude, snapshot)

    def filter_none(self):
        self.loggit.debug('"None" filter selected.  No filtering will be done.')

    def iterate_filters(self, config):
        """
        Iterate over the filters defined in `config` and execute them.



        :arg config: A dictionary of filters, as extracted from the YAML
            configuration file.

        .. note:: `config` should be a dictionary with the following form:
        .. code-block:: python

                { 'filters' : [
                        {
                            'filtertype': 'the_filter_type',
                            'key1' : 'value1',
                            ...
                            'keyN' : 'valueN'
                        }
                    ]
                }

        """
        # Make sure we actually _have_ filters to act on
        if not 'filters' in config or len(config['filters']) < 1:
            logger.info('No filters in config.  Returning unaltered object.')
            return

        self.loggit.debug('All filters: {0}'.format(config['filters']))
        for f in config['filters']:
            self.loggit.debug('Top of the loop: {0}'.format(self.snapshots))
            self.loggit.debug('Un-parsed filter args: {0}'.format(f))
            self.loggit.debug('Parsed filter args: {0}'.format(
                    SchemaCheck(
                        f,
                        filters.structure(),
                        'filter',
                        'SnapshotList.iterate_filters'
                    ).result()
                )
            )
            method = self.__map_method(f['filtertype'])
            # Remove key 'filtertype' from dictionary 'f'
            del f['filtertype']
            # If it's a filtertype with arguments, update the defaults with the
            # provided settings.
            logger.debug('Filter args: {0}'.format(f))
            logger.debug('Pre-instance: {0}'.format(self.snapshots))
            method(**f)
            logger.debug('Post-instance: {0}'.format(self.snapshots))
