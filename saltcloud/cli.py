'''
Primary interfaces for the salt-cloud system
'''
# Need to get data from 4 sources!
# CLI options
# salt cloud config - /etc/salt/cloud
# salt master config (for master integration)
# salt VM config, where VMs are defined - /etc/salt/cloud.profiles
#
# The cli, master and cloud configs will merge for opts
# the VM data will be in opts['vm']

# Import python libs
import os
import sys
import getpass
import logging

# Import salt libs
import saltcloud.config
import saltcloud.output
import salt.config
import salt.output
import salt.utils
from salt.utils.verify import verify_env, verify_files

# Import saltcloud libs
from saltcloud.utils import parsers
from saltcloud.libcloudfuncs import libcloud_version


log = logging.getLogger(__name__)


class SaltCloud(parsers.SaltCloudParser):
    def run(self):
        '''
        Execute the salt-cloud command line
        '''
        libcloud_version()

        # Parse shell arguments
        self.parse_args()

        try:
            if self.config['verify_env']:
                verify_env(
                    [os.path.dirname(self.config['conf_file'])],
                    getpass.getuser()
                )
                logfile = self.config['log_file']
                if logfile is not None and (
                        not logfile.startswith('tcp://') or
                        not logfile.startswith('udp://') or
                        not logfile.startswith('file://')):
                    # Logfile is not using Syslog, verify
                    verify_files([logfile], getpass.getuser())
        except OSError as err:
            sys.exit(err.errno)

        # Setup log file logging
        self.setup_logfile_logger()

        # Late imports so logging works as expected
        log.info('salt-cloud starting')
        import saltcloud.cloud
        mapper = saltcloud.cloud.Map(self.config)

        if self.options.update_bootstrap:
            import urllib
            url = 'http://bootstrap.saltstack.org'
            req = urllib.urlopen(url)
            deploy_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                'saltcloud', 'deploy', 'bootstrap-salt.sh'
            )
            print('Updating bootstrap-salt.sh.'
                  '\n\tSource:      {0}'
                  '\n\tDestination: {1}'.format(url, deploy_path))
            with salt.utils.fopen(deploy_path, 'w') as fp_:
                fp_.write(req.read())

        ret = {}

        if self.selected_query_option is not None:
            if self.config.get('map', None):
                log.info('Applying map from {0!r}.'.format(self.config['map']))
                try:
                    ret = mapper.interpolated_map(
                        query=self.selected_query_option
                    )
                except Exception as exc:
                    log.debug(
                        'There was an error with a custom map.', exc_info=True
                    )
                    self.error(
                        'There was an error with a custom map: {0}'.format(
                            exc
                        )
                    )
                    self.exit(1)
            else:
                try:
                    ret = mapper.map_providers(
                        query=self.selected_query_option
                    )
                except Exception as exc:
                    log.debug('There was an error with a map.', exc_info=True)
                    self.error(
                        'There was an error with a map: {0}'.format(exc)
                    )
                    self.exit(1)

        elif self.options.list_locations is not None:
            try:
                saltcloud.output.double_layer(
                    mapper.location_list(self.options.list_locations)
                )
            except Exception as exc:
                log.debug(
                    'There was an error listing locations.', exc_info=True
                )
                self.error(
                    'There was an error listing locations: {0}'.format(exc)
                )
                self.exit(1)

        elif self.options.list_images is not None:
            try:
                saltcloud.output.double_layer(
                    mapper.image_list(self.options.list_images)
                )
            except Exception as exc:
                log.debug('There was an error listing images.', exc_info=True)
                self.error(
                    'There was an error listing images: {0}'.format(exc)
                )
                self.exit(1)

        elif self.options.list_sizes is not None:
            try:
                saltcloud.output.double_layer(
                    mapper.size_list(self.options.list_sizes)
                )
            except Exception as exc:
                log.debug('There was an error listing sizes.', exc_info=True)
                self.error(
                    'There was an error listing sizes: {0}'.format(exc)
                )
                self.exit(1)

        elif self.options.destroy and (self.config.get('names', None) or
                                       self.config.get('map', None)):
            if self.config.get('map', None):
                log.info('Applying map from {0!r}.'.format(self.config['map']))
                names = mapper.delete_map(query='list_nodes')
            else:
                names = self.config.get('names', None)

            msg = 'The following virtual machines are set to be destroyed:\n'
            for name in names:
                msg += '  {0}\n'.format(name)

            try:
                if self.print_confirm(msg):
                    ret = mapper.destroy(names)
            except Exception as exc:
                log.debug(
                    'There was an error destroying machines.', exc_info=True
                )
                self.error(
                    'There was an error destroy machines: {0}'.format(exc)
                )
                self.exit(1)

        elif self.options.action and (self.config.get('names', None) or
                                      self.config.get('map', None)):
            if self.config.get('map', None):
                log.info('Applying map from {0!r}.'.format(self.config['map']))
                names = mapper.delete_map(query='list_nodes')
            else:
                names = self.config.get('names', None)

            kwargs = {}
            machines = []
            msg = (
                'The following virtual machines are set to be actioned with '
                '"{0}":\n'.format(
                    self.options.action
                )
            )
            for name in names:
                if '=' in name:
                    # This is obviously not a machine name, treat it as a kwarg
                    comps = name.split('=')
                    kwargs[comps[0]] = comps[1]
                else:
                    msg += '  {0}\n'.format(name)
                    machines.append(name)
            names = machines

            try:
                if self.print_confirm(msg):
                    ret = mapper.do_action(names, kwargs)
            except Exception as exc:
                log.debug(
                    'There was a error actioning machines.', exc_info=True
                )
                self.error(
                    'There was an error actioning machines: {0}'.format(exc)
                )
                self.exit(1)

        elif self.options.function:
            prov_func = '{0}.{1}'.format(
                self.function_provider, self.function_name
            )
            if prov_func not in mapper.clouds:
                self.error(
                    'The {0!r} provider does not define the function '
                    '{1!r}'.format(
                        self.function_provider, self.function_name
                    )
                )

            kwargs = {}
            for arg in self.args:
                if '=' in arg:
                    key, value = arg.split('=')
                    kwargs[key] = value

            try:
                ret = mapper.do_function(
                    self.function_provider, self.function_name, kwargs
                )
            except Exception as exc:
                log.debug(
                    'There was a error running the function.', exc_info=True
                )
                self.error(
                    'There was an error running the function: {0}'.format(exc)
                )
                self.exit(1)

        elif self.options.profile and self.config.get('names', False):
            try:
                ret = mapper.run_profile()
            except Exception as exc:
                log.debug('There was a profile error.', exc_info=True)
                self.error('There was a profile error: {0}'.format(exc))
                self.exit(1)

        elif self.config.get('map', None) and self.selected_query_option is None:
            if len(mapper.map) == 0:
                sys.stderr.write('No nodes defined in this map')
                self.exit(1)
            try:
                dmap = mapper.map_data()
                if 'destroy' not in dmap and len(dmap['create']) == 0:
                    sys.stderr.write('All nodes in this map already exist')
                    self.exit(1)

                log.info('Applying map from {0!r}.'.format(self.config['map']))

                msg = 'The following virtual machines are set to be created:\n'
                for name in dmap['create']:
                    msg += '  {0}\n'.format(name)
                if 'destroy' in dmap:
                    msg += ('The following virtual machines are set to be '
                            'destroyed:\n')
                    for name in dmap['destroy']:
                        msg += '  {0}\n'.format(name)

                if self.print_confirm(msg):
                    ret = mapper.run_map(dmap)

                if self.config.get('parallel', False) is False:
                    log.info('Complete')

            except Exception as exc:
                log.debug('There was a query error.', exc_info=True)
                self.error('There was a query error: {0}'.format(exc))
                self.exit(1)

        # display output using salt's outputter system
        salt.output.display_output(ret, self.options.output, self.config)
        self.exit(0)

    def print_confirm(self, msg):
        if self.options.assume_yes:
            return True
        print(msg)
        res = raw_input('Proceed? [N/y] ')
        if not res.lower().startswith('y'):
            return False
        print('... proceeding')
        return True
