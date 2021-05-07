import subprocess
import time
import sys
import httpx
import re
import os
import shutil
import json
import hashlib
import winreg
import io

from pathlib import Path

from urllib.parse import urljoin, urlparse

from datetime import datetime

from defusedxml import ElementTree

from dateutil.parser import parse as dateparse

from bs4 import BeautifulSoup

from zipfile import ZipFile

from collections.abc import Collection

from functools import partial

from eth2validatorwizard.constants import *

from eth2validatorwizard.platforms.common import (
    select_network,
    select_custom_ports,
    select_initial_state,
    select_eth1_fallbacks,
    input_dialog_default,
    search_for_generated_keys,
    get_bc_validator_deposits,
    show_whats_next,
    show_public_keys
)

from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import button_dialog, radiolist_dialog, input_dialog

RESUME_CHOCOLATEY = 'resume_chocolatey'

def installation_steps(*args, **kwargs):

    # TODO: Check time synchronization and configure it if needed

    selected_directory = select_directory()
    if not selected_directory:
        # User asked to quit
        quit_install()

    selected_network = select_network()
    if not selected_network:
        # User asked to quit
        quit_install()

    selected_ports = {
        'eth1': DEFAULT_GETH_PORT,
        'eth2_bn': DEFAULT_TEKU_BN_PORT
    }

    selected_ports = select_custom_ports(selected_ports)
    if not selected_ports:
        # User asked to quit or error
        quit_install()

    if not create_firewall_rule(selected_ports):
        # User asked to quit or error
        quit_install()
    
    if not install_chocolatey():
        # We could not install chocolatey
        quit_install()

    if not install_nssm():
        # We could not install nssm
        quit_install()

    if not install_geth(selected_directory, selected_network, selected_ports):
        # User asked to quit or error
        quit_install()
    
    generated_keys = generate_keys(selected_directory, selected_network)
    if not generated_keys:
        # User asked to quit or error
        quit_install()

    if not install_teku(selected_directory, selected_network, generated_keys, selected_ports):
        # User asked to quit or error
        quit_install()
    
    '''if not test_open_ports(selected_ports):
        # User asked to quit or error
        quit_install()'''

    if not install_monitoring(selected_directory):
        # User asked to quit or error
        quit_install()
    
    public_keys = initiate_deposit(selected_directory, selected_network, generated_keys)
    if not public_keys:
        # User asked to quit or error
        quit_install()

    show_whats_next(selected_network, generated_keys, public_keys)

    show_public_keys(selected_network, generated_keys, public_keys)

    quit_install()

def quit_install():
    print('Press enter to quit')
    input()
    sys.exit()

def create_firewall_rule(ports):
    # Add rules to Windows Firewall to make sure we can accept connections on clients ports

    geth_rule_name = 'geth'

    geth_tcp_rule_name = f'{geth_rule_name} TCP'
    geth_udp_rule_name = f'{geth_rule_name} UDP'

    breakpoint()

    print('Checking if we have a TCP firewall rule for Geth...')
    process_result = subprocess.run([
        'netsh', 'advfirewall', 'firewall', 'show', 'rule', f'name={geth_tcp_rule_name}'
    ])
    if process_result.returncode == 0:
        print('Deleting existing TCP firewall rule for Geth before creating the new one...')
        subprocess.run([
            'netsh', 'advfirewall', 'firewall', 'delete', 'rule', f'name={geth_tcp_rule_name}'
        ])
    print('Creating a new TCP firewall rule for Geth...')
    process_result = subprocess.run([
        'netsh', 'advfirewall', 'firewall', 'add', 'rule',
        f'name={geth_tcp_rule_name}',
        'dir=in',
        'action=allow',
        'service=any',
        'profile=any',
        'protocol=tcp',
        f'localport={ports["eth1"]}'
    ])

    print('Checking if we have a UDP firewall rule for Geth...')
    process_result = subprocess.run([
        'netsh', 'advfirewall', 'firewall', 'show', 'rule', f'name={geth_udp_rule_name}'
    ])
    if process_result.returncode == 0:
        print('Deleting existing UDP firewall rule for Geth before creating the new one...')
        subprocess.run([
            'netsh', 'advfirewall', 'firewall', 'delete', 'rule', f'name={geth_udp_rule_name}'
        ])
    print('Creating a new UDP firewall rule for Geth...')
    process_result = subprocess.run([
        'netsh', 'advfirewall', 'firewall', 'add', 'rule',
        f'name={geth_udp_rule_name}',
        'dir=in',
        'action=allow',
        'service=any',
        'profile=any',
        'protocol=udp',
        f'localport={ports["eth1"]}'
    ])

    teku_rule_name = 'teku'

    teku_tcp_rule_name = f'{teku_rule_name} TCP'
    teku_udp_rule_name = f'{teku_rule_name} UDP'

    print('Checking if we have a TCP firewall rule for Teku...')
    process_result = subprocess.run([
        'netsh', 'advfirewall', 'firewall', 'show', 'rule', f'name={teku_tcp_rule_name}'
    ])
    if process_result.returncode == 0:
        print('Deleting existing TCP firewall rule for Teku before creating the new one...')
        subprocess.run([
            'netsh', 'advfirewall', 'firewall', 'delete', 'rule', f'name={teku_tcp_rule_name}'
        ])
    print('Creating a new TCP firewall rule for Teku...')
    process_result = subprocess.run([
        'netsh', 'advfirewall', 'firewall', 'add', 'rule',
        f'name={teku_tcp_rule_name}',
        'dir=in',
        'action=allow',
        'service=any',
        'profile=any',
        'protocol=tcp',
        f'localport={ports["eth2_bn"]}'
    ])

    print('Checking if we have a UDP firewall rule for Teku...')
    process_result = subprocess.run([
        'netsh', 'advfirewall', 'firewall', 'show', 'rule', f'name={teku_udp_rule_name}'
    ])
    if process_result.returncode == 0:
        print('Deleting existing UDP firewall rule for Teku before creating the new one...')
        subprocess.run([
            'netsh', 'advfirewall', 'firewall', 'delete', 'rule', f'name={teku_udp_rule_name}'
        ])
    print('Creating a new UDP firewall rule for Teku...')
    process_result = subprocess.run([
        'netsh', 'advfirewall', 'firewall', 'add', 'rule',
        f'name={teku_udp_rule_name}',
        'dir=in',
        'action=allow',
        'service=any',
        'profile=any',
        'protocol=udp',
        f'localport={ports["eth2_bn"]}'
    ])

    return True

def install_chocolatey():
    # Install chocolatey to obtain other tools

    # Check to see if choco is already installed
    choco_installed = False

    try:
        process_result = subprocess.run(['choco', '--version'])

        if process_result.returncode == 0:
            choco_installed = True
            
            print('Chocolatey is already installed, we will update it to the latest version')
            subprocess.run([
                'choco', 'upgrade', 'chocolatey'])

    except FileNotFoundError:
        choco_installed = False

    if choco_installed:
        return True

    print('Chocolatey is not installed, we will install it')
    subprocess.run([
        'powershell', '-Command',
        "& {Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))}"
        ])

    return True

def install_nssm():
    # Install nssm for service management

    nssm_path = Path(CHOCOLATEY_DEFAULT_BIN_PATH, 'nssm')

    # Check to see if nssm is already installed
    nssm_installed = False

    try:
        process_result = subprocess.run(['nssm', '--version'])

        if process_result.returncode == 0:
            nssm_installed = True
        
    except FileNotFoundError:
        try:
            process_result = subprocess.run([str(nssm_path), '--version'])

            if process_result.returncode == 0:
                nssm_installed = True
        except FileNotFoundError:
            nssm_installed = False
    
    if nssm_installed:
        print('NSSM is already installed, no need to install it')
        return True

    choco_path = Path(CHOCOLATEY_DEFAULT_BIN_PATH, 'choco')

    # Check to see if choco is installed
    choco_installed = False

    try:
        process_result = subprocess.run(['choco', '--version'])

        if process_result.returncode == 0:
            choco_installed = True
    except FileNotFoundError:
        try:
            process_result = subprocess.run([str(choco_path), '--version'])

            if process_result.returncode == 0:
                choco_installed = True
        except FileNotFoundError:
            choco_installed = False

    if not choco_installed:
        print('We could not find choco. You might need to close this '
            'window and restart the wizard to continue.')
        return False
    
    try:
        subprocess.run([
            'choco', 'install', '-y', 'nssm'])
    except FileNotFoundError:
        subprocess.run([
            str(choco_path), 'install', '-y', 'nssm'])
    
    return True
    
def select_directory():
    directory_valid = False
    selected_directory = None
    input_canceled = False
    default_directory = r'c:\ethereum'

    while not directory_valid:
        not_valid_msg = ''
        if selected_directory is not None:
            not_valid_msg = (
'''

<style bg="red" fg="black">Your last input was <b>an invalid directory</b>. Please make sure to enter a valid
directory.</style>'''
            )

        default_input_text = default_directory

        if selected_directory is not None:
            default_input_text = selected_directory

        selected_directory = input_dialog_default(
            title='Enter a directory',
            text=(HTML(
f'''
Please enter a directory where ethereum clients and their data will be
stored:

Ideally you want to select an empty directory that does not contain any
space or international character in its path. You also want to make sure
you select a directory on your fast disk that has enough space for ethereum
data.

If the directory does not exist, we will attempt to create it for you.

* Press the tab key to switch between the controls below{not_valid_msg}
'''         )),
            default_input_text=default_input_text).run()

        if not selected_directory:
            input_canceled = True
            break
        
        directory_valid = directory_validator(selected_directory)

    if input_canceled:
        # User clicked the cancel button
        return False

    return Path(selected_directory)

def directory_validator(directory):
    try:
        directory_path = Path(directory)
        directory_path.mkdir(parents=True, exist_ok=True)
        return directory_path.is_dir()
    except OSError:
        return False

    return False

def get_nssm_binary():
    # Check for nssm install and path
    nssm_path = Path(CHOCOLATEY_DEFAULT_BIN_PATH, 'nssm')
    nssm_binary = 'nssm'

    nssm_installed = False

    try:
        process_result = subprocess.run(['nssm', '--version'])

        if process_result.returncode == 0:
            nssm_installed = True
        
    except FileNotFoundError:
        try:
            process_result = subprocess.run([str(nssm_path), '--version'])

            if process_result.returncode == 0:
                nssm_installed = True
                nssm_binary = nssm_path
        except FileNotFoundError:
            nssm_installed = False
    
    if not nssm_installed:
        print('NSSM is not installed, we cannot continue.')
        return False
    
    return nssm_binary

def install_geth(base_directory, network, ports):
    # Install geth for the selected network

    nssm_binary = get_nssm_binary()
    if not nssm_binary:
        return False

    # Check for existing service
    geth_service_exists = False
    geth_service_name = 'geth'

    service_details = get_service_details(nssm_binary, geth_service_name)

    if service_details is not None:
        geth_service_exists = True

    if geth_service_exists:
        result = button_dialog(
            title='Geth service found',
            text=(
f'''
The geth service seems to have already been created. Here are some details
found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

Do you want to skip installing geth and its service?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result

        if result == 1:
            return True
        
        # User wants to proceed, make sure the geth service is stopped first
        subprocess.run([
            str(nssm_binary), 'stop', geth_service_name])

    result = button_dialog(
        title='Geth installation',
        text=(
'''
This next step will install Geth, an Eth1 client.

It will download the official binary, verify its PGP signature and extract
it for easy use.

Once the installation is completed, it will create a system service that
will automatically start Geth on reboot or if it crashes. Geth will be
started and you will slowly start syncing with the Ethereum 1.0 network.
This syncing process can take a few hours or days even with good hardware
and good internet. We will perform a few tests to make sure Geth is running
properly.
'''     ),
        buttons=[
            ('Install', True),
            ('Quit', False)
        ]
    ).run()

    if not result:
        return result

    # Check if geth is already installed
    geth_path = base_directory.joinpath('bin', 'geth.exe')

    geth_found = False
    geth_version = 'unknown'

    if geth_path.is_file():
        try:
            process_result = subprocess.run([
                str(geth_path), 'version'
                ], capture_output=True, text=True, encoding='utf8')
            geth_found = True

            process_output = process_result.stdout
            result = re.search(r'Version: (.*?)\n', process_output)
            if result:
                geth_version = result.group(1).strip()

        except FileNotFoundError:
            pass
    
    install_geth_binary = True

    if geth_found:
        result = button_dialog(
            title='Geth binary found',
            text=(
f'''
The geth binary seems to have already been installed. Here are some
details found:

Version: {geth_version}
Location: {geth_path}

Do you want to skip installing the geth binary?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        install_geth_binary = (result == 2)

    if install_geth_binary:
        # Install Geth from official website
        
        # Get list of geth releases/builds from their store
        next_marker = None
        page_end_found = False

        windows_builds = []

        try:
            print('Getting geth builds...')
            while not page_end_found:
                params = GETH_STORE_BUILDS_PARAMS.copy()
                if next_marker is not None:
                    params['marker'] = next_marker

                response = httpx.get(GETH_STORE_BUILDS_URL, params=params)

                if response.status_code != 200:
                    print(f'Cannot connect to geth builds URL {GETH_STORE_BUILDS_URL}.\n'
                    f'Unexpected status code {response.status_code}')
                    return False
                
                builds_tree_root = ElementTree.fromstring(response.text)
                blobs = builds_tree_root.findall('.//Blobs/Blob')

                for blob in blobs:
                    build_name = blob.find('Name').text.strip()
                    if build_name.endswith('.asc'):
                        continue

                    if not is_stable_windows_amd64_archive(build_name):
                        continue

                    build_properties = blob.find('Properties')
                    last_modified_date = dateparse(build_properties.find('Last-Modified').text)

                    windows_builds.append({
                        'name': build_name,
                        'last_modified_date': last_modified_date
                    })

                next_marker = builds_tree_root.find('.//NextMarker').text
                if next_marker is None:
                    page_end_found = True

        except httpx.RequestError as exception:
            print(f'Cannot connect to geth builds URL {GETH_STORE_BUILDS_URL}.\nException {exception}')
            return False

        if len(windows_builds) <= 0:
            print('No geth builds found on geth store. We cannot continue.')
            return False

        # Download latest geth build and its signature
        windows_builds.sort(key=lambda x: (x['last_modified_date'], x['name']), reverse=True)
        latest_build = windows_builds[0]

        download_path = base_directory.joinpath('downloads')
        download_path.mkdir(parents=True, exist_ok=True)

        geth_archive_path = download_path.joinpath(latest_build['name'])
        if geth_archive_path.is_file():
            geth_archive_path.unlink()

        latest_build_url = urljoin(GETH_BUILDS_BASE_URL, latest_build['name'])

        try:
            with open(geth_archive_path, 'wb') as binary_file:
                print(f'Downloading geth archive {latest_build["name"]}...')
                with httpx.stream('GET', latest_build_url) as http_stream:
                    if http_stream.status_code != 200:
                        print(f'Cannot download geth archive {latest_build_url}.\n'
                            f'Unexpected status code {http_stream.status_code}')
                        return False
                    for data in http_stream.iter_bytes():
                        binary_file.write(data)
        except httpx.RequestError as exception:
            print(f'Exception while downloading geth archive. Exception {exception}')
            return False

        geth_archive_sig_path = download_path.joinpath(latest_build['name'] + '.asc')
        if geth_archive_sig_path.is_file():
            geth_archive_sig_path.unlink()

        latest_build_sig_url = urljoin(GETH_BUILDS_BASE_URL, latest_build['name'] + '.asc')

        try:
            with open(geth_archive_sig_path, 'wb') as binary_file:
                print(f'Downloading geth archive signature {latest_build["name"]}.asc...')
                with httpx.stream('GET', latest_build_sig_url) as http_stream:
                    if http_stream.status_code != 200:
                        print(f'Cannot download geth archive signature {latest_build_sig_url}.\n'
                            f'Unexpected status code {http_stream.status_code}')
                        return False
                    for data in http_stream.iter_bytes():
                        binary_file.write(data)
        except httpx.RequestError as exception:
            print(f'Exception while downloading geth archive signature. Exception {exception}')
            return False

        if not install_gpg(base_directory):
            return False
        
        # Verify PGP signature
        gpg_binary_path = base_directory.joinpath('bin', 'gpg.exe')

        print('Downloading geth Windows Builder PGP key...')

        command_line = [str(gpg_binary_path), '--keyserver', 'pool.sks-keyservers.net',
            '--recv-keys', GETH_WINDOWS_PGP_KEY_ID]
        process_result = subprocess.run(command_line)

        retry_count = 5
        if process_result.returncode != 0:
            # GPG failed to download Sigma Prime's PGP key, let's wait and retry a few times
            retry_index = 0
            while process_result.returncode != 0 and retry_index < retry_count:
                retry_index = retry_index + 1
                print('GPG failed to download the PGP key. We will wait 10 seconds and try again.')
                time.sleep(10)
                process_result = subprocess.run(command_line)
        
        if process_result.returncode != 0:
            # TODO: Better handling of failed PGP key download
            print(
f'''
We failed to download the Geth Windows Builder PGP key to verify the geth
archive after {retry_count} retries.
'''
)
            return False
        
        process_result = subprocess.run([
            str(gpg_binary_path), '--verify', str(geth_archive_sig_path)])
        if process_result.returncode != 0:
            # TODO: Better handling of failed PGP signature
            print('The geth archive signature is wrong. We\'ll stop here to protect you.')
            return False
        
        # Remove download leftovers
        geth_archive_sig_path.unlink()        

        # Unzip geth archive
        bin_path = base_directory.joinpath('bin')
        bin_path.mkdir(parents=True, exist_ok=True)

        geth_extracted_binary = None

        with ZipFile(geth_archive_path, 'r') as zip_file:
            for name in zip_file.namelist():
                if name.endswith('geth.exe'):
                    geth_extracted_binary = Path(zip_file.extract(name, download_path))
        
        # Remove download leftovers
        geth_archive_path.unlink()

        if geth_extracted_binary is None:
            print('The geth binary was not found in the archive. We cannot continue.')
            return False

        # Move geth back into bin directory
        target_geth_binary_path = bin_path.joinpath('geth.exe')
        if target_geth_binary_path.is_file():
            target_geth_binary_path.unlink()
        
        geth_extracted_binary.rename(target_geth_binary_path)

        geth_extracted_binary.parent.rmdir()
    
    # Check if Geth directory already exists
    geth_datadir = base_directory.joinpath('var', 'lib', 'goethereum')
    if geth_datadir.is_dir():
        geth_datadir_size = sizeof_fmt(get_dir_size(geth_datadir))

        result = button_dialog(
            title='Geth data directory found',
            text=(
f'''
An existing geth data directory has been found. Here are some
details found:

Location: {geth_datadir}
Size: {geth_datadir_size}

Do you want to remove this directory first and start from nothing?
'''         ),
            buttons=[
                ('Remove', 1),
                ('Keep', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        if result == 1:
            shutil.rmtree(geth_datadir)

    # Setup Geth directory
    geth_datadir.mkdir(parents=True, exist_ok=True)
    
    # Setup Geth service
    log_path = base_directory.joinpath('var', 'log')
    log_path.mkdir(parents=True, exist_ok=True)

    geth_stdout_log_path = log_path.joinpath('geth-service-stdout.log')
    geth_stderr_log_path = log_path.joinpath('geth-service-stderr.log')

    if geth_stdout_log_path.is_file():
        geth_stdout_log_path.unlink()
    if geth_stderr_log_path.is_file():
        geth_stderr_log_path.unlink()

    geth_arguments = GETH_ARGUMENTS[network]
    geth_arguments.append('--datadir')
    geth_arguments.append(str(geth_datadir))
    if ports['eth1'] != DEFAULT_GETH_PORT:
        geth_arguments.append('--port')
        geth_arguments.append(str(ports['eth1']))

    parameters = {
        'DisplayName': GETH_SERVICE_DISPLAY_NAME[network],
        'AppRotateFiles': '1',
        'AppRotateSeconds': '86400',
        'AppRotateBytes': '10485760',
        'AppStdout': str(geth_stdout_log_path),
        'AppStderr': str(geth_stderr_log_path)
    }

    if not create_service(nssm_binary, geth_service_name, geth_path, geth_arguments, parameters):
        print('There was an issue creating the geth service. We cannot continue.')
        return False
    
    print('Starting geth service...')
    process_result = subprocess.run([
        str(nssm_binary), 'start', geth_service_name
    ])

    delay = 15
    print(f'We are giving {delay} seconds for the geth service to start properly.')
    time.sleep(delay)
    
    # Verify proper Geth service installation
    service_details = get_service_details(nssm_binary, geth_service_name)
    if not service_details:
        print('We could not find the geth service we just created. We cannot continue.')
        return False

    if not (
        service_details['status'] == WINDOWS_SERVICE_RUNNING):

        result = button_dialog(
            title='Geth service not running properly',
            text=(
f'''
The geth service we just created seems to have issues. Here are some
details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

We cannot proceed if the geth service cannot be started properly. Make sure
to check the logs and fix any issue found there. You can see the logs in:

{geth_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your geth service logs, inspect the following file:

{geth_stderr_log_path}
'''
        )

        return False

    # Iterate over the logs and output them for around 30 seconds
    log_read_index = 0
    for i in range(6):
        log_text = ''
        with open(geth_stderr_log_path, 'r', encoding='utf8') as log_file:
            log_file.seek(log_read_index)
            log_text = log_file.read()
            log_read_index = log_file.tell()
        
        log_length = len(log_text)

        if log_length > 0:
            print(log_text)
        time.sleep(5)

    # Verify proper Geth syncing
    local_geth_jsonrpc_url = 'http://127.0.0.1:8545'
    request_json = {
        'jsonrpc': '2.0',
        'method': 'eth_syncing',
        'id': 1
    }
    headers = {
        'Content-Type': 'application/json'
    }
    try:
        response = httpx.post(local_geth_jsonrpc_url, json=request_json, headers=headers)
    except httpx.RequestError as exception:
        result = button_dialog(
            title='Cannot connect to Geth',
            text=(
f'''
We could not connect to geth HTTP-RPC server. Here are some details for
this last test we tried to perform:

URL: {local_geth_jsonrpc_url}
Method: POST
Headers: {headers}
JSON payload: {json.dumps(request_json)}
Exception: {exception}

We cannot proceed if the geth HTTP-RPC server is not responding properly.
Make sure to check the logs and fix any issue found there. You can see the
logs in:

{geth_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your geth service logs, inspect the following file:

{geth_stderr_log_path}
'''
        )

        return False

    if response.status_code != 200:
        result = button_dialog(
            title='Cannot connect to Geth',
            text=(
f'''
We could not connect to geth HTTP-RPC server. Here are some details for
this last test we tried to perform:

URL: {local_geth_jsonrpc_url}
Method: POST
Headers: {headers}
JSON payload: {json.dumps(request_json)}
Status code: {response.status_code}

We cannot proceed if the geth HTTP-RPC server is not responding properly.
Make sure to check the logs and fix any issue found there. You can see the
logs in:

{geth_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your geth service logs, inspect the following file:

{geth_stderr_log_path}
'''
        )

        return False
    
    response_json = response.json()

    retry_index = 0
    retry_count = 5

    while (
        not response_json or
        'result' not in response_json or
        not response_json['result']
    ) and retry_index < retry_count:
        result = button_dialog(
            title='Unexpected response from Geth',
            text=(
f'''
We received an unexpected response from geth HTTP-RPC server. This is
likely because geth has not started syncing yet or because it's taking a
little longer to find peers. We suggest you wait and retry in a minute.
Here are some details for this last test we tried to perform:

URL: {local_geth_jsonrpc_url}
Method: POST
Headers: {headers}
JSON payload: {json.dumps(request_json)}
Response: {json.dumps(response_json)}

We cannot proceed if the geth HTTP-RPC server is not responding properly.
Make sure to check the logs and fix any issue found there. You can see the
logs in:

{geth_stderr_log_path}
'''         ),
            buttons=[
                ('Retry', 1),
                ('Quit', False)
            ]
        ).run()

        if not result:

            print(
f'''
To examine your geth service logs, inspect the following file:

{geth_stderr_log_path}
'''
            )

            return False
        
        retry_index = retry_index + 1

        # Wait a little before the next retry
        time.sleep(5)

        try:
            response = httpx.post(local_geth_jsonrpc_url, json=request_json, headers=headers)
        except httpx.RequestError as exception:
            result = button_dialog(
                title='Cannot connect to Geth',
                text=(
f'''
We could not connect to geth HTTP-RPC server. Here are some details for
this last test we tried to perform:

URL: {local_geth_jsonrpc_url}
Method: POST
Headers: {headers}
JSON payload: {json.dumps(request_json)}
Exception: {exception}

We cannot proceed if the geth HTTP-RPC server is not responding properly.
Make sure to check the logs and fix any issue found there. You can see the
logs in:

{geth_stderr_log_path}
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            print(
f'''
To examine your geth service logs, inspect the following file:

{geth_stderr_log_path}
'''
            )

            return False

        if response.status_code != 200:
            result = button_dialog(
                title='Cannot connect to Geth',
                text=(
f'''
We could not connect to geth HTTP-RPC server. Here are some details for
this last test we tried to perform:

URL: {local_geth_jsonrpc_url}
Method: POST
Headers: {headers}
JSON payload: {json.dumps(request_json)}
Status code: {response.status_code}

We cannot proceed if the geth HTTP-RPC server is not responding properly.
Make sure to check the logs and fix any issue found there. You can see the
logs in:

{geth_stderr_log_path}
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            print(
f'''
To examine your geth service logs, inspect the following file:

{geth_stderr_log_path}
'''
            )

            return False

        response_json = response.json()

    if (
        not response_json or
        'result' not in response_json or
        not response_json['result']
    ):
        # We could not get a proper result from Geth after all those retries
        result = button_dialog(
            title='Unexpected response from Geth',
            text=(
f'''
After a few retries, we still received an unexpected response from geth
HTTP-RPC server. Here are some details for this last test we tried to
perform:

URL: {local_geth_jsonrpc_url}
Method: POST
Headers: {headers}
JSON payload: {json.dumps(request_json)}
Response: {json.dumps(response_json)}

We cannot proceed if the geth HTTP-RPC server is not responding properly.
Make sure to check the logs and fix any issue found there. You can see the
logs in:

{geth_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your geth service logs, inspect the following file:

{geth_stderr_log_path}
'''
        )

        return False

    response_result = response_json['result']

    if 'currentBlock' not in response_result:
        result = button_dialog(
            title='Unexpected response from Geth',
            text=(
f'''
The response from the eth_syncing JSON-RPC call on Geth HTTP-RPC server
was unexpected. Here are some details for this call:

result field: {json.dumps(response_result)}

We cannot proceed if the geth HTTP-RPC server is not responding properly.
Make sure to check the logs and fix any issue found there. You can see the
logs in:

{geth_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your geth service logs, inspect the following file:

{geth_stderr_log_path}
'''
        )

        return False

    # TODO: Using async and prompt_toolkit asyncio loop to display syncing values updating
    # in realtime for a few seconds

    print(
f'''
Geth is currently syncing properly.

currentBlock: {int(response_result.get('currentBlock', '0x0'), base=16)}
highestBlock: {int(response_result.get('highestBlock', '0x0'), base=16)}
knownStates: {int(response_result.get('knownStates', '0x0'), base=16)}
pulledStates: {int(response_result.get('pulledStates', '0x0'), base=16)}
startingBlock: {int(response_result.get('startingBlock', '0x0'), base=16)}

Raw result: {response_result}
''')
    time.sleep(5)

    return True

def create_service(nssm_binary, service_name, binary_path, binary_args, parameters=None):
    # Create a Windows service using NSSM and configure it

    # Stop the service first if it exists
    subprocess.run([
        str(nssm_binary), 'stop', service_name
    ])

    # Remove the service to make sure it does not exist
    subprocess.run([
        str(nssm_binary), 'remove', service_name, 'confirm'
    ])

    # Install the service
    process_result = subprocess.run([
        str(nssm_binary), 'install', service_name, str(binary_path)
        ] + binary_args)

    if process_result.returncode != 0:
        print(f'Unexpected return code from NSSM when installing a new service. '
            f'Return code {process_result.returncode}')
        return False

    # Set all the other parameters
    if parameters is not None:
        for param, value in parameters.items():
            if type(value) is str:
                process_result = subprocess.run([
                    str(nssm_binary), 'set', service_name, param, value
                    ])
            elif isinstance(value, Collection):
                process_result = subprocess.run([
                    str(nssm_binary), 'set', service_name, param
                    ] + list(value))
            else:
                print(f'Unexpected parameter value {value} for parameter {param}.')
                return False
            
            if process_result.returncode != 0:
                print(f'Unexpected return code from NSSM when modifying at parameter. '
                    f'Return code {process_result.returncode}')
                return False
    
    return True

def get_service_details(nssm_binary, service):
    # Return some service details

    process_result = subprocess.run([
        str(nssm_binary), 'dump', service
        ], capture_output=True, text=True, encoding='utf8')
    
    if process_result.returncode != 0:
        return None

    service_details = {
        'install': None,
        'status': None,
        'parameters': {}
    }

    process_output = process_result.stdout
    result = re.search(r'nssm\.exe install \S+( (?P<install>.+))?', process_output)
    if result:
        service_details['install'] = result.group('install')

    for result in re.finditer(r'nssm.exe set \S+( (?P<param>\S+))?( (?P<quote>")?(?P<value>.+?)(?P=quote)?)?(\n|$)', process_output):
        param = result.group('param')
        value = result.group('value')
        if param is not None:
            service_details['parameters'][param] = value
    
    process_result = subprocess.run([
        str(nssm_binary), 'status', service
        ], capture_output=True, text=True, encoding='utf8')
    
    if process_result.returncode == 0:
        process_output = process_result.stdout
        service_details['status'] = process_output.strip()

    return service_details

def is_stable_windows_amd64_archive(name):
    return (
        name.find('windows') != -1 and
        name.endswith('.zip') and
        name.find('amd64') != -1 and
        name.find('unstable') == -1 and
        name.find('alltools') == -1
    )

def install_gpg(base_directory):
    # Install the GPG binary

    # Check if gnupg is already installed
    gpg_installed = False

    gpg_binary_path = base_directory.joinpath('bin', 'gpg.exe')

    if gpg_binary_path.is_file():
        process_result = subprocess.run([
            str(gpg_binary_path), '--version'
        ])

        if process_result.returncode == 0:
            gpg_installed = True

    if gpg_installed:
        print('GNUPG is already installed, no need to install it')
        return True

    # Get the gnupg install URL
    gpg_installer_url = None
    try:
        response = httpx.get(GNUPG_DOWNLOAD_URL)
        
        if response.status_code != 200:
            print(f'Cannot connect to GNUPG download URL {GNUPG_DOWNLOAD_URL}.\n'
                f'Unexpected status code {response.status_code}')
            return False
        
        response_text = response.text
        match = re.search(r'href="(?P<url>[^"]+gnupg-w32-[^"]+.exe)"', response_text)
        if not match:
            print(f'Cannot find GNUPG installer on GNUPG download URL {GNUPG_DOWNLOAD_URL}.')
            return False
        
        gpg_installer_url = urljoin(GNUPG_DOWNLOAD_URL, match.group('url'))
    except httpx.RequestError as exception:
        print(f'Cannot connect to GNUPG download URL {GNUPG_DOWNLOAD_URL}.\nException {exception}')
        return False

    if gpg_installer_url is None:
        return False
    
    download_path = base_directory.joinpath('downloads')
    download_path.mkdir(parents=True, exist_ok=True)

    # Download the gnupg installer
    file_name = urlparse(gpg_installer_url).path.split('/')[-1]
    download_installer_path = download_path.joinpath(file_name)

    if download_installer_path.is_file():
        download_installer_path.unlink()

    try:
        with open(download_installer_path, 'wb') as binary_file:
            print('Downloading GNUPG installer...')
            with httpx.stream('GET', gpg_installer_url) as http_stream:
                if http_stream.status_code != 200:
                    print(f'Cannot download GNUPG installer {gpg_installer_url}.\n'
                        f'Unexpected status code {http_stream.status_code}')
                    return False
                for data in http_stream.iter_bytes():
                    binary_file.write(data)
    except httpx.RequestError as exception:
        print(f'Exception while downloading GNUPG installer. Exception {exception}')
        return False

    # Run installer silently
    print('Installing GNUPG...')

    process_result = subprocess.run([
        str(download_installer_path), '/S', '/D=' + str(base_directory)
    ])

    if process_result.returncode != 0:
        print(f'Failed to install GNUPG. Return code {process_result.returncode}')
        return False

    # Remove download leftovers
    download_installer_path.unlink()

    if not gpg_binary_path.is_file():
        print(f'Could not find GPG binary after installation. Expected to be in {gpg_binary_path}')
        return False
    
    process_result = subprocess.run([
        str(gpg_binary_path), '--version'
    ])

    if process_result.returncode != 0:
        print(f'Unexpected return from gpg binary. Return code {process_result.returncode}')
        return False

    return True

def install_jre(base_directory):
    # Install adoptopenjdk jre

    # Check if jre is already installed
    jre_path = base_directory.joinpath('bin', 'jre')
    java_path = jre_path.joinpath('bin', 'java.exe')

    jre_found = False
    jre_version = 'unknown'

    if java_path.is_file():
        try:
            process_result = subprocess.run([
                str(java_path), '--version'
                ], capture_output=True, text=True, encoding='utf8')
            jre_found = True

            process_output = process_result.stdout
            result = re.search(r'OpenJDK Runtime Environment (.*?)\n', process_output)
            if result:
                jre_version = result.group(1).strip()

        except FileNotFoundError:
            pass
    
    install_jre = True

    if jre_found:
        result = button_dialog(
            title='JRE found',
            text=(
f'''
The JRE seems to have already been installed. Here are some details found:

Version: {jre_version}
Location: {jre_path}

Do you want to skip installing the JRE?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        install_jre = (result == 2)
    
    if install_jre:
        windows_builds = []

        try:
            print('Getting JRE builds...')

            response = httpx.get(ADOPTOPENJDK_11_API_URL, params=ADOPTOPENJDK_11_API_PARAMs)

            if response.status_code != 200:
                print(f'Cannot connect to JRE builds URL {ADOPTOPENJDK_11_API_URL}.\n'
                f'Unexpected status code {response.status_code}')
                return False
            
            response_json = response.json()

            if (
                type(response_json) is not list or
                len(response_json) == 0 or
                type(response_json[0]) is not dict or
                'binaries' not in response_json[0]):
                print(f'Unexpected response from JRE builds URL {ADOPTOPENJDK_11_API_URL}')
                return False
            
            binaries = response_json[0]['binaries']
            for binary in binaries:
                if (
                    'architecture' not in binary or
                    'os' not in binary or
                    'package' not in binary or
                    'image_type' not in binary or
                    'updated_at' not in binary):
                    continue
                image_type = binary['image_type']
                architecture = binary['architecture']
                binary_os = binary['os']

                if not (
                    binary_os == 'windows' and
                    architecture == 'x64' and
                    image_type == 'jre'):
                    continue

                package = binary['package']
                updated_at = dateparse(binary['updated_at'])

                if (
                    'name' not in package or
                    'checksum' not in package or
                    'link' not in package):
                    print(f'Unexpected response from JRE builds URL {ADOPTOPENJDK_11_API_URL} in package')
                    return False
                
                package_name = package['name']
                package_link = package['link']
                package_checksum = package['checksum']

                windows_builds.append({
                    'name': package_name,
                    'updated_at': updated_at,
                    'link': package_link,
                    'checksum': package_checksum
                })

        except httpx.RequestError as exception:
            print(f'Cannot connect to JRE builds URL {ADOPTOPENJDK_11_API_URL}.\nException {exception}')
            return False

        if len(windows_builds) <= 0:
            print('No JRE builds found on adoptopenjdk.net. We cannot continue.')
            return False
        
        # Download latest JRE build and its signature
        windows_builds.sort(key=lambda x: (x['updated_at'], x['name']), reverse=True)
        latest_build = windows_builds[0]

        download_path = base_directory.joinpath('downloads')
        download_path.mkdir(parents=True, exist_ok=True)

        jre_archive_path = download_path.joinpath(latest_build['name'])
        if jre_archive_path.is_file():
            jre_archive_path.unlink()

        try:
            with open(jre_archive_path, 'wb') as binary_file:
                print(f'Downloading JRE archive {latest_build["name"]}...')
                with httpx.stream('GET', latest_build['link']) as http_stream:
                    if http_stream.status_code != 200:
                        print(f'Cannot download JRE archive {latest_build["link"]}.\n'
                            f'Unexpected status code {http_stream.status_code}')
                        return False
                    for data in http_stream.iter_bytes():
                        binary_file.write(data)
        except httpx.RequestError as exception:
            print(f'Exception while downloading JRE archive. Exception {exception}')
            return False
        
        # Unzip JRE archive
        archive_members = None

        print(f'Extracting JRE archive {latest_build["name"]}...')
        with ZipFile(jre_archive_path, 'r') as zip_file:
            archive_members = zip_file.namelist()
            zip_file.extractall(download_path)
        
        # Remove download leftovers
        jre_archive_path.unlink()

        if archive_members is None or len(archive_members) == 0:
            print('No files found in JRE archive. We cannot continue.')
            return False
        
        # Move all those extracted files into their final destination
        if jre_path.is_dir():
            shutil.rmtree(jre_path)
        jre_path.mkdir(parents=True, exist_ok=True)

        archive_extracted_dir = download_path.joinpath(Path(archive_members[0]).parts[0])

        with os.scandir(archive_extracted_dir) as it:
            for diritem in it:
                shutil.move(diritem.path, jre_path)
            
        # Make sure jre was installed properly
        jre_found = False
        try:
            process_result = subprocess.run([
                str(java_path), '--version'
                ], capture_output=True, text=True, encoding='utf8')
            jre_found = True

            process_output = process_result.stdout
            result = re.search(r'OpenJDK Runtime Environment (.*?)\n', process_output)
            if result:
                jre_version = result.group(1).strip()

        except FileNotFoundError:
            pass
    
        if not jre_found:
            print(f'We could not find the java binary from the installed JRE in {java_path}. '
                f'We cannot continue.')
            return False
    
    return True

def install_teku(base_directory, network, keys, ports):
    # Install Teku for the selected network

    nssm_binary = get_nssm_binary()
    if not nssm_binary:
        return False

    # Check for existing service
    teku_service_exists = False
    teku_service_name = 'teku'

    service_details = get_service_details(nssm_binary, teku_service_name)

    if service_details is not None:
        teku_service_exists = True
    
    if teku_service_exists:
        result = button_dialog(
            title='Teku service found',
            text=(
f'''
The teku service seems to have already been created. Here are some details
found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

Do you want to skip installing teku and its service?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        if result == 1:
            return True
        
        # User wants to proceed, make sure the teku service is stopped first
        subprocess.run([
            str(nssm_binary), 'stop', teku_service_name])

    result = button_dialog(
        title='Teku installation',
        text=(
'''
This next step will install Teku, an Eth2 client that includes a
beacon node and a validator client in the same binary distribution.

It will install AdoptOpenJDK, a Java Runtime Environment, it will download
the official Teku binary distribution from GitHub, it will verify its
checksum and it will extract it for easy use. You will be invited to
provide an initial state to fast-track syncing.

Once installed locally, it will create a service that will automatically
start Teku on reboot or if it crashes. The Teku client will be started and
you will start syncing with the Ethereum 2.0 network. The Teku client will
automatically start validating once syncing is completed and your
validator(s) are activated.
'''     ),
        buttons=[
            ('Install', True),
            ('Quit', False)
        ]
    ).run()

    if not result:
        return result
    
    if not install_jre(base_directory):
        return False

    # Check if teku is already installed
    teku_path = base_directory.joinpath('bin', 'teku')
    teku_batch_file = teku_path.joinpath('bin', 'teku.bat')

    teku_found = False
    teku_version = 'unknown'

    java_home = base_directory.joinpath('bin', 'jre')

    if teku_batch_file.is_file():
        try:
            env = os.environ.copy()
            env['JAVA_HOME'] = str(java_home)

            process_result = subprocess.run([
                str(teku_batch_file), '--version'
                ], capture_output=True, text=True, env=env)
            teku_found = True

            process_output = process_result.stdout
            result = re.search(r'teku/(?P<version>[^/]+)', process_output)
            if result:
                teku_version = result.group('version').strip()

        except FileNotFoundError:
            pass
    
    install_teku_binary = True

    if teku_found:
        result = button_dialog(
            title='Teku binary distribution found',
            text=(
f'''
The teku binary distribution seems to have already been installed. Here are
some details found:

Version: {teku_version}
Location: {teku_path}

Do you want to skip installing the teku binary distribution?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        install_teku_binary = (result == 2)
    
    if install_teku_binary:
        # Getting latest Teku release files
        teku_gh_release_url = GITHUB_REST_API_URL + TEKU_LATEST_RELEASE
        headers = {'Accept': GITHUB_API_VERSION}
        try:
            response = httpx.get(teku_gh_release_url, headers=headers)
        except httpx.RequestError as exception:
            print(f'Cannot connect to Github. Exception {exception}')
            return False

        if response.status_code != 200:
            # TODO: Better handling for network response issue
            print(f'Github returned error code. Status code {response.status_code}')
            return False
        
        release_json = response.json()

        if 'body' not in release_json:
            print('Unexpected response from github release. We cannot continue.')
            return False
        
        release_desc = release_json['body']

        zip_url = None
        zip_sha256 = None

        result = re.search(r'\[zip\]\((?P<url>[^\)]+)\)\s*\(\s*sha256\s*:?\s*`(?P<sha256>[^`]+)`\s*\)',
            release_desc)
        if result:
            zip_url = result.group('url')
            if zip_url is not None:
                zip_url = zip_url.strip()
            
            zip_sha256 = result.group('sha256')
            if zip_sha256 is not None:
                zip_sha256 = zip_sha256.strip()
        

        if zip_url is None or zip_sha256 is None:
            # TODO: Better handling of missing zip or checksum in latest release
            print('Could not find binary distribution zip or checksum in Github release body. '
                'We cannot continue.')
            return False
        
        # Downloading latest Teku binary distribution archive
        download_path = base_directory.joinpath('downloads')
        download_path.mkdir(parents=True, exist_ok=True)

        url_file_name = urlparse(zip_url).path.split('/')[-1]

        teku_archive_path = download_path.joinpath(url_file_name)
        teku_archive_hash = hashlib.sha256()
        if teku_archive_path.is_file():
            teku_archive_path.unlink()

        try:
            with open(teku_archive_path, 'wb') as binary_file:
                print(f'Downloading teku archive {url_file_name}...')
                with httpx.stream('GET', zip_url) as http_stream:
                    if http_stream.status_code != 200:
                        print(f'Cannot download teku archive {zip_url}.\n'
                            f'Unexpected status code {http_stream.status_code}')
                        return False
                    for data in http_stream.iter_bytes():
                        binary_file.write(data)
                        teku_archive_hash.update(data)
        except httpx.RequestError as exception:
            print(f'Exception while downloading teku archive. Exception {exception}')
            return False

        # Verify checksum
        print('Verifying teku archive checksum...')
        teku_archive_hexdigest = teku_archive_hash.hexdigest()
        if teku_archive_hexdigest.lower() != zip_sha256.lower():
            print('Teku archive checksum does not match. We will stop here to protect you.')
            return False
        
        # Unzip teku archive
        archive_members = None

        print(f'Extracting teku archive {url_file_name}...')
        with ZipFile(teku_archive_path, 'r') as zip_file:
            archive_members = zip_file.namelist()
            zip_file.extractall(download_path)
        
        # Remove download leftovers
        teku_archive_path.unlink()

        if archive_members is None or len(archive_members) == 0:
            print('No files found in teku archive. We cannot continue.')
            return False
        
        # Move all those extracted files into their final destination
        if teku_path.is_dir():
            shutil.rmtree(teku_path)
        teku_path.mkdir(parents=True, exist_ok=True)

        archive_extracted_dir = download_path.joinpath(Path(archive_members[0]).parts[0])

        with os.scandir(archive_extracted_dir) as it:
            for diritem in it:
                shutil.move(diritem.path, teku_path)
            
        # Make sure teku was installed properly
        teku_found = False
        if teku_batch_file.is_file():
            try:
                env = os.environ.copy()
                env['JAVA_HOME'] = str(java_home)

                process_result = subprocess.run([
                    str(teku_batch_file), '--version'
                    ], capture_output=True, text=True, env=env)
                teku_found = True

                process_output = process_result.stdout
                result = re.search(r'teku/(?P<version>[^/]+)', process_output)
                if result:
                    teku_version = result.group('version').strip()

            except FileNotFoundError:
                pass
    
        if not teku_found:
            print(f'We could not find the teku binary distribution from the installed archive '
                f'in {teku_path}. We cannot continue.')
            return False
        else:
            print(f'Teku version {teku_version} installed.')

    # Check if teku directory already exists
    teku_datadir = base_directory.joinpath('var', 'lib', 'teku')
    if teku_datadir.is_dir():
        teku_datadir_size = sizeof_fmt(get_dir_size(teku_datadir))

        result = button_dialog(
            title='Teku data directory found',
            text=(
f'''
An existing teku data directory has been found. Here are some
details found:

Location: {teku_datadir}
Size: {teku_datadir_size}

Do you want to remove this directory first and start from nothing?
'''         ),
            buttons=[
                ('Remove', 1),
                ('Keep', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        if result == 1:
            shutil.rmtree(teku_datadir)

    # Get initial state provider
    initial_state_url = select_initial_state(network)
    if type(initial_state_url) is not str and not initial_state_url:
        return False

    # Get eth1 fallbacks from user
    eth1_fallbacks = select_eth1_fallbacks(network)
    if type(eth1_fallbacks) is not list and not eth1_fallbacks:
        return False

    # Setup teku directory
    teku_datadir.mkdir(parents=True, exist_ok=True)

    # Setup teku service
    log_path = base_directory.joinpath('var', 'log')
    log_path.mkdir(parents=True, exist_ok=True)

    heap_dump_path = base_directory.joinpath('var', 'dump', 'teku')
    heap_dump_path.mkdir(parents=True, exist_ok=True)

    teku_stdout_log_path = log_path.joinpath('teku-service-stdout.log')
    teku_stderr_log_path = log_path.joinpath('teku-service-stderr.log')

    if teku_stdout_log_path.is_file():
        teku_stdout_log_path.unlink()
    if teku_stderr_log_path.is_file():
        teku_stderr_log_path.unlink()

    eth1_endpoints = ['http://127.0.0.1:8545'] + eth1_fallbacks

    teku_arguments = TEKU_ARGUMENTS[network]
    teku_arguments.append('--eth1-endpoints=' + ','.join(eth1_endpoints))
    teku_arguments.append('--data-path=' + str(teku_datadir))
    teku_arguments.append('--validator-keys=' + str(keys['validator_keys_path']) +
        ';' + str(keys['validator_keys_path']))
    if initial_state_url != '':
        teku_arguments.append('--initial-state=' + initial_state_url)
    if ports['eth2_bn'] != DEFAULT_TEKU_BN_PORT:
        teku_arguments.append('--p2p-port==' + str(ports['eth2_bn']))

    parameters = {
        'DisplayName': TEKU_SERVICE_DISPLAY_NAME[network],
        'AppRotateFiles': '1',
        'AppRotateSeconds': '86400',
        'AppRotateBytes': '10485760',
        'AppStdout': str(teku_stdout_log_path),
        'AppStderr': str(teku_stderr_log_path),
        'AppEnvironmentExtra': [
            'JAVA_HOME=' + str(java_home),
            'JAVA_OPTS=-Xmx4g',
            'TEKU_OPTS=-XX:HeapDumpPath=' + str(heap_dump_path)
        ]
    }

    if not create_service(nssm_binary, teku_service_name, teku_batch_file, teku_arguments,
        parameters):
        print('There was an issue creating the teku service. We cannot continue.')
        return False

    print('Starting teku service...')
    process_result = subprocess.run([
        str(nssm_binary), 'start', teku_service_name
    ])

    delay = 15
    print(f'We are giving {delay} seconds for the teku service to start properly.')
    time.sleep(delay)

    # Verify proper Teku service installation
    service_details = get_service_details(nssm_binary, teku_service_name)
    if not service_details:
        print('We could not find the teku service we just created. '
            'We cannot continue.')
        return False

    if not (
        service_details['status'] == WINDOWS_SERVICE_RUNNING):

        # Check for evidence of wrong password file
        if teku_stderr_log_path.is_file():
            log_part = ''
            with open(teku_stderr_log_path, 'r', encoding='utf8') as log_file:
                log_part = log_file.read(1024)
            result = re.search(r'Failed to decrypt', log_part)
            if result:
                subprocess.run([
                    str(nssm_binary), 'stop', teku_service_name])
                
                print(
f'''
Your password file contains the wrong password. Teku cannot be started. You
might need to generate your keys again or fix your password file. We cannot
continue.

Your password files are the .txt files in:

{keys['validator_keys_path']}
'''             )
                return False

        result = button_dialog(
            title='Teku service not running properly',
            text=(
f'''
The teku service we just created seems to have issues. Here are some
details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

We cannot proceed if the teku service cannot be started properly. Make sure
to check the logs and fix any issue found there. You can see the logs in:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        # Stop the service to prevent indefinite restart attempts
        subprocess.run([
            str(nssm_binary), 'stop', teku_service_name])

        print(
f'''
To examine your teku service logs, inspect the following files:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''
        )

        return False

    # Iterate over the logs and output them for around 30 seconds
    out_log_read_index = 0
    err_log_read_index = 0
    for i in range(6):
        out_log_text = ''
        with open(teku_stdout_log_path, 'r', encoding='utf8') as log_file:
            log_file.seek(out_log_read_index)
            out_log_text = log_file.read()
            out_log_read_index = log_file.tell()
        
        err_log_text = ''
        with open(teku_stderr_log_path, 'r', encoding='utf8') as log_file:
            log_file.seek(err_log_read_index)
            err_log_text = log_file.read()
            err_log_read_index = log_file.tell()
        
        out_log_length = len(out_log_text)
        if out_log_length > 0:
            print(out_log_text)

        err_log_length = len(err_log_text)
        if err_log_length > 0:
            print(err_log_text)

        time.sleep(5)

    # Verify proper Teku installation and syncing
    local_teku_http_base = 'http://127.0.0.1:5051'
    
    teku_version_query = '/eth/v1/node/version'
    teku_query_url = local_teku_http_base + teku_version_query
    headers = {
        'accept': 'application/json'
    }
    try:
        response = httpx.get(teku_query_url, headers=headers)
    except httpx.RequestError as exception:

        # Check for evidence of wrong password file
        if teku_stderr_log_path.is_file():
            log_part = ''
            with open(teku_stderr_log_path, 'r', encoding='utf8') as log_file:
                log_part = log_file.read(1024)
            result = re.search(r'Failed to decrypt', log_part)
            if result:
                subprocess.run([
                    str(nssm_binary), 'stop', teku_service_name])
                
                print(
f'''
Your password file contains the wrong password. Teku cannot be started. You
might need to generate your keys again or fix your password file. We cannot
continue.

Your password files are the .txt files in:

{keys['validator_keys_path']}
'''             )
                return False

        result = button_dialog(
            title='Cannot connect to Teku',
            text=(
f'''
We could not connect to teku HTTP server. Here are some details for this
last test we tried to perform:

URL: {teku_query_url}
Method: GET
Headers: {headers}
Exception: {exception}

We cannot proceed if the teku HTTP server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your teku service logs, inspect the following files:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''
        )

        return False

    if response.status_code != 200:
        result = button_dialog(
            title='Cannot connect to Teku',
            text=(
f'''
We could not connect to teku HTTP server. Here are some details for this
last test we tried to perform:

URL: {teku_query_url}
Method: GET
Headers: {headers}
Status code: {response.status_code}

We cannot proceed if the teku HTTP server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your teku service logs, inspect the following files:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''
        )

        return False
    
    # Verify proper Teku syncing
    teku_syncing_query = '/eth/v1/node/syncing'
    teku_query_url = local_teku_http_base + teku_syncing_query
    headers = {
        'accept': 'application/json'
    }
    try:
        response = httpx.get(teku_query_url, headers=headers)
    except httpx.RequestError as exception:
        button_dialog(
            title='Cannot connect to Teku',
            text=(
f'''
We could not connect to teku HTTP server. Here are some details for this
last test we tried to perform:

URL: {teku_query_url}
Method: GET
Headers: {headers}
Exception: {exception}

We cannot proceed if the teku HTTP server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your teku service logs, inspect the following files:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''
        )

        return False

    if response.status_code != 200:
        button_dialog(
            title='Cannot connect to Teku',
            text=(
f'''
We could not connect to teku HTTP server. Here are some details for this
last test we tried to perform:

URL: {teku_query_url}
Method: GET
Headers: {headers}
Status code: {response.status_code}

We cannot proceed if the teku HTTP server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your teku service logs, inspect the following files:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''
        )

        return False
    
    response_json = response.json()

    retry_index = 0
    retry_count = 5

    while (
        'data' not in response_json or
        'is_syncing' not in response_json['data'] or
        not response_json['data']['is_syncing']
    ) and retry_index < retry_count:
        result = button_dialog(
            title='Unexpected response from Teku',
            text=(
f'''
We received an unexpected response from the teku HTTP server. This is
likely because teku has not started syncing yet or because it's taking a
little longer to find peers. We suggest you wait and retry in a minute.
Here are some details for this last test we tried to perform:

URL: {teku_query_url}
Method: GET
Headers: {headers}
Response: {json.dumps(response_json)}

We cannot proceed if the teku HTTP server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''         ),
            buttons=[
                ('Retry', 1),
                ('Quit', False)
            ]
        ).run()
        
        if not result:

            print(
f'''
To examine your teku service logs, inspect the following files:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''
            )

            return False
        
        retry_index = retry_index + 1

        # Wait a little before the next retry
        time.sleep(5)

        try:
            response = httpx.get(teku_query_url, headers=headers)
        except httpx.RequestError as exception:
            button_dialog(
                title='Cannot connect to Teku',
                text=(
f'''
We could not connect to teku HTTP server. Here are some details for this
last test we tried to perform:

URL: {teku_query_url}
Method: GET
Headers: {headers}
Exception: {exception}

We cannot proceed if the teku HTTP server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''          ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            print(
f'''
To examine your teku service logs, inspect the following files:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''
            )

            return False

        if response.status_code != 200:
            button_dialog(
                title='Cannot connect to Teku',
                text=(
f'''
We could not connect to teku HTTP server. Here are some details for this
last test we tried to perform:

URL: {teku_query_url}
Method: GET
Headers: {headers}
Status code: {response.status_code}

We cannot proceed if the teku HTTP server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''          ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            print(
f'''
To examine your teku service logs, inspect the following files:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''
            )

            return False
        
        response_json = response.json()
    
    if (
        'data' not in response_json or
        'is_syncing' not in response_json['data'] or
        not response_json['data']['is_syncing']
    ):
        # We could not get a proper result from the Teku after all those retries
        result = button_dialog(
            title='Unexpected response from Teku',
            text=(
f'''
After a few retries, we still received an unexpected response from the
teku HTTP server. Here are some details for this last test we tried to
perform:

URL: {teku_query_url}
Method: GET
Headers: {headers}
Response: {json.dumps(response_json)}

We cannot proceed if the teku HTTP server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your teku service logs, inspect the following files:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''
        )

        return False

    # TODO: Using async and prompt_toolkit asyncio loop to display syncing values updating
    # in realtime for a few seconds

    print(
f'''
Teku is currently syncing properly.

Head slot: {response_json['data'].get('head_slot', 'unknown')}
Sync distance: {response_json['data'].get('sync_distance', 'unknown')}

Raw data: {response_json['data']}
''' )
    time.sleep(5)

    return True

def generate_keys(base_directory, network):
    # Generate validator keys for the selected network

    # Check if there are keys already created
    keys_path = base_directory.joinpath('var', 'lib', 'eth2', 'keys')

    # Ensure we currently have ACL permission to read from the keys path
    if keys_path.is_dir():
        subprocess.run([
            'icacls', str(keys_path), '/inheritancelevel:e'
        ])

    # Check if there are keys already created
    deposit_data_directory = base_directory.joinpath('var', 'lib', 'eth2', 'deposit')
    target_deposit_data_path = deposit_data_directory.joinpath('deposit_data.json')

    generated_keys = search_for_generated_keys(keys_path)

    deposit_data_file = 'unknown'
    if target_deposit_data_path.is_file():
        deposit_data_file = target_deposit_data_path
    elif generated_keys['deposit_data_path'] is not None:
        deposit_data_file = generated_keys['deposit_data_path']
    
    if (
        len(generated_keys['keystore_paths']) > 0 or
        len(generated_keys['password_paths']) > 0
    ):
        result = button_dialog(
            title='Validator keys already created',
            text=(
f'''
It seems like validator keys have already been created. Here are some
details found:

Number of keystores: {len(generated_keys['keystore_paths'])}
Number of associated password files: {len(generated_keys['password_paths'])}
Deposit data file: {deposit_data_file}
Location: {keys_path}

Do you want to skip generating new keys? Generating new keys will destroy
all previously generated keys and deposit data file.
'''         ),
            buttons=[
                ('Skip', 1),
                ('Generate', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        if result == 1:
            return generated_keys

    currency = NETWORK_CURRENCY[network]

    result = button_dialog(
        title='Generating keys',
        text=(HTML(
f'''
This next step will generate the keys needed to be a validator.

It will download the official eth2.0-deposit-cli binary from GitHub,
verify its SHA256 checksum, extract it and start it.

The eth2.0-deposit-cli tool is executed in an interactive way where you
have to answer a few questions. It will help you create a mnemonic from
which all your keys will be derived from. The mnemonic is the ultimate key.
It is <style bg="red" fg="black"><b>VERY IMPORTANT</b></style> to securely and privately store your mnemonic. It can
be used to recreate your validator keys and eventually withdraw your funds.

When asked how many validators you wish to run, remember that you will have
to do a 32 {currency} deposit for each validator.
'''     )),
        buttons=[
            ('Generate', True),
            ('Quit', False)
        ]
    ).run()

    if not result:
        return result
    
    result = button_dialog(
        title='CAUTION',
        text=(HTML(
f'''
<style bg="red" fg="black">If the <b>mnemonic</b> you are about to create is lost or stolen, you will also
lose your funds.</style>
'''     )),
        buttons=[
            ('Understood', True),
            ('Quit', False)
        ]
    ).run()

    if not result:
        return result
    
    # Check if eth2.0-deposit-cli is already installed
    eth2_deposit_cli_binary = base_directory.joinpath('bin', 'deposit.exe')

    eth2_deposit_found = False

    if eth2_deposit_cli_binary.is_file():
        try:
            process_result = subprocess.run([
                str(eth2_deposit_cli_binary), '--help'
                ], capture_output=True, text=True)
            eth2_deposit_found = True

            # TODO: Validate the output of deposit --help to make sure it's fine? Maybe?
            # process_output = process_result.stdout

        except FileNotFoundError:
            pass
    
    install_eth2_deposit_binary = True

    if eth2_deposit_found:
        result = button_dialog(
            title='eth2.0-deposit-cli binary found',
            text=(
f'''
The eth2.0-deposit-cli binary seems to have already been installed. Here
are some details found:

Location: {eth2_deposit_cli_binary}

Do you want to skip installing the eth2.0-deposit-cli binary?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        install_eth2_deposit_binary = (result == 2)

    if install_eth2_deposit_binary:
        # Getting latest eth2.0-deposit-cli release files
        eth2_cli_gh_release_url = GITHUB_REST_API_URL + ETH2_DEPOSIT_CLI_LATEST_RELEASE
        headers = {'Accept': GITHUB_API_VERSION}
        try:
            response = httpx.get(eth2_cli_gh_release_url, headers=headers)
        except httpx.RequestError as exception:
            # TODO: Better handling for network response issue
            print(
f'Cannot get latest eth2.0-deposit-cli release from Github. Exception {exception}'
            )
            return False

        if response.status_code != 200:
            # TODO: Better handling for network response issue
            print(
f'Cannot get latest eth2.0-deposit-cli release from Github. Error code {response.status_code}'
            )
            return False
        
        release_json = response.json()

        if 'assets' not in release_json:
            # TODO: Better handling on unexpected response structure
            print('Unexpected response from Github API.')
            return False
        
        binary_asset = None
        checksum_asset = None

        for asset in release_json['assets']:
            if 'name' not in asset:
                continue
            if 'browser_download_url' not in asset:
                continue
        
            file_name = asset['name']
            file_url = asset['browser_download_url']

            if file_name.endswith('windows-amd64.zip'):
                binary_asset = {
                    'file_name': file_name,
                    'file_url': file_url
                }
            elif file_name.endswith('windows-amd64.sha256'):
                checksum_asset = {
                    'file_name': file_name,
                    'file_url': file_url
                }
        
        if binary_asset is None:
            # TODO: Better handling of missing binary in latest release
            print('No eth2.0-deposit-cli binary found in Github release')
            return False
        
        checksum_path = None

        if checksum_asset is None:
            # TODO: Better handling of missing checksum in latest release
            print('Warning: No eth2.0-deposit-cli checksum found in Github release')
        
        # Downloading latest eth2.0-deposit-cli release files
        download_path = base_directory.joinpath('downloads')
        download_path.mkdir(parents=True, exist_ok=True)

        binary_path = Path(download_path, binary_asset['file_name'])
        binary_hash = hashlib.sha256()

        if binary_path.is_file():
            binary_path.unlink()

        try:
            with open(binary_path, 'wb') as binary_file:
                print(f'Downloading eth2.0-deposit-cli binary {binary_asset["file_name"]}...')
                with httpx.stream('GET', binary_asset['file_url']) as http_stream:
                    if http_stream.status_code != 200:
                        print(f'Cannot download eth2.0-deposit-cli binary from Github '
                            f'{binary_asset["file_url"]}.\nUnexpected status code '
                            f'{http_stream.status_code}')
                        return False
                    for data in http_stream.iter_bytes():
                        binary_file.write(data)
                        binary_hash.update(data)
        except httpx.RequestError as exception:
            print(f'Exception while downloading eth2.0-deposit-cli binary from Github. '
                f'Exception {exception}')
            return False

        if checksum_asset is not None:
            binary_hexdigest = binary_hash.hexdigest()

            checksum_path = Path(download_path, checksum_asset['file_name'])

            if checksum_path.is_file():
                checksum_path.unlink()

            try:
                with open(checksum_path, 'wb') as signature_file:
                    print(f'Downloading eth2.0-deposit-cli checksum {checksum_asset["file_name"]}...')
                    with httpx.stream('GET', checksum_asset['file_url']) as http_stream:
                        if http_stream.status_code != 200:
                            print(f'Cannot download eth2.0-deposit-cli checksum from Github '
                                f'{checksum_asset["file_url"]}.\nUnexpected status code '
                                f'{http_stream.status_code}')
                            return False
                        for data in http_stream.iter_bytes():
                            signature_file.write(data)
            except httpx.RequestError as exception:
                print(f'Exception while downloading eth2.0-deposit-cli checksum from Github. '
                    f'Exception {exception}')
                return False

            # Verify SHA256 signature
            print('Verifying eth2.0-deposit-cli checksum...')
            checksum_value = ''
            with open(checksum_path, 'r', encoding='utf_16_le') as signature_file:
                checksum_value = signature_file.read(1024).strip()
            
            # Remove download leftovers
            checksum_path.unlink()

            # Remove BOM
            if checksum_value.startswith('\ufeff'):
                checksum_value = checksum_value[1:]
            if binary_hexdigest != checksum_value:
                # TODO: Better handling of failed SHA256 checksum
                print('SHA256 checksum failed on eth2.0-deposit-cli binary from Github. '
                    'We will stop here to protect you.')
                return False
        
        # Unzip eth2.0-deposit-cli archive
        bin_path = base_directory.joinpath('bin')
        bin_path.mkdir(parents=True, exist_ok=True)

        deposit_extracted_binary = None

        print(f'Extracting eth2.0-deposit-cli binary {binary_asset["file_name"]}...')
        with ZipFile(binary_path, 'r') as zip_file:
            for name in zip_file.namelist():
                if name.endswith('deposit.exe'):
                    deposit_extracted_binary = Path(zip_file.extract(name, download_path))
        
        # Remove download leftovers
        binary_path.unlink()

        if deposit_extracted_binary is None:
            print('The eth2.0-deposit-cli binary was not found in the archive. '
                'We cannot continue.')
            return False

        # Move deposit binary back into bin directory
        target_deposit_binary_path = bin_path.joinpath('deposit.exe')
        if target_deposit_binary_path.is_file():
            target_deposit_binary_path.unlink()
        
        deposit_extracted_binary.rename(target_deposit_binary_path)

        deposit_extracted_binary.parent.rmdir()

    # Clean potential leftover keys
    if keys_path.is_dir():
        shutil.rmtree(keys_path)
    keys_path.mkdir(parents=True, exist_ok=True)
    
    # Launch eth2.0-deposit-cli
    print('Generating keys with eth2.0-deposit-cli binary...')
    subprocess.run([
        str(eth2_deposit_cli_binary), 'new-mnemonic', '--chain', network, '--folder', str(keys_path)],
        cwd=keys_path)

    # Clean up eth2.0-deposit-cli binary
    eth2_deposit_cli_binary.unlink()

    # Reorganize generated files to move them up a directory
    validator_keys_path = keys_path.joinpath('validator_keys')
    if validator_keys_path.is_dir():
        with os.scandir(validator_keys_path) as it:
            for entry in it:
                if not entry.is_file():
                    continue
                target_path = keys_path.joinpath(entry.name)
                os.rename(entry.path, target_path)
        
        validator_keys_path.rmdir()

    # Verify the generated keys
    generated_keys = search_for_generated_keys(keys_path)
    
    if generated_keys['deposit_data_path'] is None or len(generated_keys['keystore_paths']) == 0:
        # TODO: Better handling of no keys generated
        print('No key has been generated with the eth2.0-deposit-cli tool. We cannot continue.')
        return False
    
    # Move deposit data file outside of keys directory
    if deposit_data_directory.is_dir():
        shutil.rmtree(deposit_data_directory)
    deposit_data_directory.mkdir(parents=True, exist_ok=True)
    
    os.rename(generated_keys['deposit_data_path'], target_deposit_data_path)

    # Generate password files
    keystore_password = input_dialog(
        title='Enter your keystore password',
        text=(
f'''
Please enter the password you just used to create your keystore with the
eth2.0-deposit-cli tool:

The password will be stored in a text file so that Teku can access your
validator keys when starting. Permissions will be changed so that only
the local system account can access the keys and the password file.

* Press the tab key to switch between the controls below
'''     ),
        password=True).run()

    if not keystore_password:
        return False

    with os.scandir(keys_path) as it:
        for entry in it:
            if not entry.is_file():
                continue
            if not entry.name.startswith('keystore'):
                continue
            if not entry.name.endswith('.json'):
                continue

            entry_path = Path(entry.path)
            target_file = keys_path.joinpath(entry_path.stem + '.txt')
            with open(target_file, 'w', encoding='utf8') as password_file:
                password_file.write(keystore_password)

    generated_keys = search_for_generated_keys(keys_path)

    # Change ACL to protect keys directory
    subprocess.run([
        'icacls', str(keys_path), '/grant', 'SYSTEM:F', '/t'
    ])

    subprocess.run([
        'icacls', str(keys_path), '/inheritancelevel:r'
    ])

    return generated_keys

def initiate_deposit(base_directory, network, keys):
    # Initiate and explain the deposit on launchpad

    launchpad_url = LAUNCHPAD_URLS[network]
    currency = NETWORK_CURRENCY[network]

    # Find the deposit file
    deposit_file_path = base_directory.joinpath('var', 'lib', 'eth2', 'deposit',
        'deposit_data.json')
    if not deposit_file_path.is_file():
        print(f'We could not find the deposit data file in {deposit_file_path} . If you already '
            f'performed your deposit on the launchpad, you should be good. If not, there was '
            f'an issue somewhere during the installation.')
        return False

    # TODO: Create an alternative way to easily obtain the deposit file with a simple HTTP server

    result = button_dialog(
        title='Deposit on the launchpad',
        text=(
f'''
This next step is to perform the 32 {currency} deposit(s) on the launchpad. In
order to do this deposit, you will need your deposit file which was created
during the key generation step. Your deposit file can be found in

{deposit_file_path}

On the Eth2 Launchpad website, you will be asked a few questions and it
will explain some of the risks and mitigation strategies. Make sure to read
everything carefully and make sure you understand it all. When you are
ready, go to the following URL in your browser:

{launchpad_url}

When you are done with the deposit(s), click the "I'm done" button below.
'''     ),
        buttons=[
            ('I\'m done', True),
            ('Quit', False)
        ]
    ).run()

    if not result:
        return result

    public_keys = []

    with open(deposit_file_path, 'r', encoding='utf8') as deposit_data_file:
        deposit_data = json.loads(deposit_data_file.read(204800))
        
        for validator_data in deposit_data:
            if 'pubkey' not in validator_data:
                continue
            public_key = validator_data['pubkey']
            public_keys.append('0x' + public_key)
    
    if len(public_keys) == 0:
        # TODO: Better handling of no public keys in deposit data file
        print('No public key(s) found in the deposit file.')
        return False

    # Verify that the deposit was done correctly using beaconcha.in API
    validator_deposits = get_bc_validator_deposits(network, public_keys)

    if type(validator_deposits) is not list and not validator_deposits:
        # TODO: Better handling of unability to get validator(s) deposits from beaconcha.in
        print('Unability to get validator(s) deposits from beaconcha.in')
        return False

    while len(validator_deposits) == 0:
        # beaconcha.in does not see any validator with the public keys we generated

        result = button_dialog(
            title='No deposit found',
            text=(
f'''
No deposit has been found on the beaconcha.in website for the validator
keys that you generated. In order to become an active validator, you need
to do a 32 {currency} deposit for each validator you created. In order to do
this deposit, you will need your deposit file which was created during the
key generation step. Your deposit file can be found in

{deposit_file_path}

To perform the deposit(s), go to the following URL in your browser:

{launchpad_url}

When you are done with the deposit(s), click the "I'm done" button below.
Note that it can take a few minutes before beaconcha.in sees your
deposit(s).
'''     ),
            buttons=[
                ('I\'m done', True),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result

        validator_deposits = get_bc_validator_deposits(network, public_keys)

        if type(validator_deposits) is not list and not validator_deposits:
            # TODO: Better handling of unability to get validator(s) deposits from beaconcha.in
            print('Unability to get validator(s) deposits from beaconcha.in')
            return False
    
    # Check if all the deposit(s) were done for each validator
    while len(validator_deposits) < len(public_keys):

        result = button_dialog(
            title='Missing deposit(s)',
            text=(
f'''
Only {len(validator_deposits)} deposit(s) has been found for your {len(public_keys)} validators on the
beaconcha.in website. In order to become an active validator, you need
to do a 32 {currency} deposit for each validator you created. In order to do
this deposit, you will need your deposit file which was created during the
key generation step. Your deposit file can be found in

{deposit_file_path}

To perform the deposit(s), go to the following URL in your browser:

{launchpad_url}

When you are done with the deposit(s), click the "I'm done" button below.
Note that it can take a few minutes before beaconcha.in sees your
deposit(s).
'''     ),
            buttons=[
                ('I\'m done', True),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result

        validator_deposits = get_bc_validator_deposits(network, public_keys)

        if type(validator_deposits) is not list and not validator_deposits:
            # TODO: Better handling of unability to get validator(s) deposits from beaconcha.in
            print('Unability to get validator(s) deposits from beaconcha.in')
            return False

    # Clean up deposit data file
    deposit_file_path.unlink()
    
    return public_keys

def install_monitoring(base_directory):

    result = button_dialog(
        title='Monitoring installation',
        text=(
'''
This next step is optional but recommended. It will install Prometheus,
Grafana and Windows Exporter so you can easily monitor your machine's
resources, Geth, Teku and your validator(s).

It will download the official Prometheus binary distribution from GitHub,
it will download the official Grafana binary distribution their official
website and it will download the official Windows Exporter binary
distribution from GitHub.

Once installed locally, it will create a service that will automatically
start Prometheus, Grafana and Windows Exporter on reboot or if they crash.
'''     ),
        buttons=[
            ('Install', 1),
            ('Skip', 2),
            ('Quit', False)
        ]
    ).run()

    if result == 2:
        return True

    if not result:
        return result
    
    if not install_prometheus(base_directory):
        return False
    
    if not install_windows_exporter(base_directory):
        return False
    
    if not install_grafana(base_directory):
        return False
    
    # Show message on how to use monitoring
    result = button_dialog(
        title='Monitoring has been installed successfully',
        text=(
f'''
Everything needed for basic monitoring has been installed correctly.

You can access your Grafana server on: http://localhost:3000/

There is already an administrator user with the username: admin . You can
login with the default password: admin . On first login, you will be asked
to change your password.

Once logged in, you should be able to see various dashboards for Geth,
Teku and your system resources.
'''         ),
        buttons=[
            ('Keep going', True),
            ('Quit', False)
        ]
    ).run()

    return result

def install_prometheus(base_directory):
    # Install Prometheus as a service

    nssm_binary = get_nssm_binary()
    if not nssm_binary:
        return False

    # Check for existing service
    prometheus_service_exists = False
    prometheus_service_name = 'prometheus'

    service_details = get_service_details(nssm_binary, prometheus_service_name)

    if service_details is not None:
        prometheus_service_exists = True
    
    if prometheus_service_exists:
        result = button_dialog(
            title='Prometheus service found',
            text=(
f'''
The prometheus service seems to have already been created. Here are some
details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

Do you want to skip installing prometheus and its service?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        if result == 1:
            return True
        
        # User wants to proceed, make sure the prometheus service is stopped first
        subprocess.run([
            str(nssm_binary), 'stop', prometheus_service_name])

    # Check if prometheus is already installed
    prometheus_path = base_directory.joinpath('bin', 'prometheus')
    prometheus_binary_file = prometheus_path.joinpath('prometheus.exe')

    prometheus_found = False
    prometheus_version = 'unknown'

    if prometheus_binary_file.is_file():
        try:
            process_result = subprocess.run([
                str(prometheus_binary_file), '--version'
                ], capture_output=True, text=True)
            prometheus_found = True

            process_output = process_result.stdout
            result = re.search(r'prometheus, version (?P<version>[^ ]+)', process_output)
            if result:
                prometheus_version = result.group('version').strip()

        except FileNotFoundError:
            pass
    
    install_prometheus_binary = True

    if prometheus_found:
        result = button_dialog(
            title='Prometheus binary distribution found',
            text=(
f'''
The prometheus binary distribution seems to have already been installed.
Here are some details found:

Version: {prometheus_version}
Location: {prometheus_path}

Do you want to skip installing the prometheus binary distribution?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        install_prometheus_binary = (result == 2)
    
    if install_prometheus_binary:
        # Getting latest Prometheus release files
        prometheus_gh_release_url = GITHUB_REST_API_URL + PROMETHEUS_LATEST_RELEASE
        headers = {'Accept': GITHUB_API_VERSION}
        try:
            response = httpx.get(prometheus_gh_release_url, headers=headers)
        except httpx.RequestError as exception:
            print(f'Cannot connect to Github. Exception {exception}')
            return False

        if response.status_code != 200:
            # TODO: Better handling for network response issue
            print(f'Github returned error code. Status code {response.status_code}')
            return False
        
        release_json = response.json()

        if 'assets' not in release_json:
            # TODO: Better handling on unexpected response structure
            print('Unexpected response from Github API.')
            return False
        
        binary_asset = None

        for asset in release_json['assets']:
            if 'name' not in asset:
                continue
            if 'browser_download_url' not in asset:
                continue
        
            file_name = asset['name']
            file_url = asset['browser_download_url']

            if file_name.endswith('windows-amd64.zip'):
                binary_asset = {
                    'file_name': file_name,
                    'file_url': file_url
                }
                break
        
        if binary_asset is None:
            # TODO: Better handling of missing binary in latest release
            print('No prometheus binary distribution found in Github release')
            return False
        
        # Downloading latest Prometheus binary distribution archive
        download_path = base_directory.joinpath('downloads')
        download_path.mkdir(parents=True, exist_ok=True)

        url_file_name = binary_asset['file_name']
        zip_url = binary_asset['file_url']

        prometheus_archive_path = download_path.joinpath(url_file_name)
        prometheus_archive_hash = hashlib.sha256()
        if prometheus_archive_path.is_file():
            prometheus_archive_path.unlink()

        try:
            with open(prometheus_archive_path, 'wb') as binary_file:
                print(f'Downloading prometheus archive {url_file_name}...')
                with httpx.stream('GET', zip_url) as http_stream:
                    if http_stream.status_code != 200:
                        print(f'Cannot download prometheus archive {zip_url}.\n'
                            f'Unexpected status code {http_stream.status_code}')
                        return False
                    for data in http_stream.iter_bytes():
                        binary_file.write(data)
                        prometheus_archive_hash.update(data)
        except httpx.RequestError as exception:
            print(f'Exception while downloading prometheus archive. Exception {exception}')
            return False
        
        # Unzip prometheus archive
        archive_members = None

        print(f'Extracting prometheus archive {url_file_name}...')
        with ZipFile(prometheus_archive_path, 'r') as zip_file:
            archive_members = zip_file.namelist()
            zip_file.extractall(download_path)
        
        # Remove download leftovers
        prometheus_archive_path.unlink()

        if archive_members is None or len(archive_members) == 0:
            print('No files found in prometheus archive. We cannot continue.')
            return False
        
        # Move all those extracted files into their final destination
        if prometheus_path.is_dir():
            shutil.rmtree(prometheus_path)
        prometheus_path.mkdir(parents=True, exist_ok=True)

        archive_extracted_dir = download_path.joinpath(Path(archive_members[0]).parts[0])

        with os.scandir(archive_extracted_dir) as it:
            for diritem in it:
                shutil.move(diritem.path, prometheus_path)
            
        # Make sure prometheus was installed properly
        prometheus_found = False
        if prometheus_binary_file.is_file():
            try:
                process_result = subprocess.run([
                    str(prometheus_binary_file), '--version'
                    ], capture_output=True, text=True)
                prometheus_found = True

                process_output = process_result.stdout
                result = re.search(r'prometheus, version (?P<version>[^ ]+)', process_output)
                if result:
                    prometheus_version = result.group('version').strip()

            except FileNotFoundError:
                pass
    
        if not prometheus_found:
            print(f'We could not find the prometheus binary distribution from the installed '
                f'archive in {prometheus_path}. We cannot continue.')
            return False
        else:
            print(f'Prometheus version {prometheus_version} installed.')

    # Check if prometheus directory already exists
    prometheus_datadir = base_directory.joinpath('var', 'lib', 'prometheus')
    if prometheus_datadir.is_dir():
        prometheus_datadir_size = sizeof_fmt(get_dir_size(prometheus_datadir))

        result = button_dialog(
            title='Prometheus data directory found',
            text=(
f'''
An existing prometheus data directory has been found. Here are some details
found:

Location: {prometheus_datadir}
Size: {prometheus_datadir_size}

Do you want to remove this directory first and start from nothing?
'''         ),
            buttons=[
                ('Remove', 1),
                ('Keep', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        if result == 1:
            shutil.rmtree(prometheus_datadir)

    # Setup prometheus directory
    prometheus_datadir.mkdir(parents=True, exist_ok=True)

    # Setup prometheus config file
    prometheus_config_path = base_directory.joinpath('etc', 'prometheus')
    if not prometheus_config_path.is_dir():
        prometheus_config_path.mkdir(parents=True, exist_ok=True)
    
    prometheus_config_file = prometheus_config_path.joinpath('prometheus.yml')
    if prometheus_config_file.is_file():
        prometheus_config_file.unlink()
    
    with open(str(prometheus_config_file), 'w', encoding='utf8') as config_file:
        config_file.write(PROMETHEUS_CONFIG_WINDOWS)

    # Setup prometheus service
    log_path = base_directory.joinpath('var', 'log')
    log_path.mkdir(parents=True, exist_ok=True)

    prometheus_stdout_log_path = log_path.joinpath('prometheus-service-stdout.log')
    prometheus_stderr_log_path = log_path.joinpath('prometheus-service-stderr.log')

    if prometheus_stdout_log_path.is_file():
        prometheus_stdout_log_path.unlink()
    if prometheus_stderr_log_path.is_file():
        prometheus_stderr_log_path.unlink()

    prometheus_arguments = PROMETHEUS_ARGUMENTS
    prometheus_arguments.append('--config.file="' + str(prometheus_config_file) + '"')
    prometheus_arguments.append('--storage.tsdb.path="' + str(prometheus_datadir) + '"')

    parameters = {
        'DisplayName': PROMETHEUS_SERVICE_DISPLAY_NAME,
        'AppRotateFiles': '1',
        'AppRotateSeconds': '86400',
        'AppRotateBytes': '10485760',
        'AppStdout': str(prometheus_stdout_log_path),
        'AppStderr': str(prometheus_stderr_log_path)
    }

    if not create_service(nssm_binary, prometheus_service_name, prometheus_binary_file,
        prometheus_arguments, parameters):
        print('There was an issue creating the prometheus service. We cannot continue.')
        return False

    print('Starting prometheus service...')
    process_result = subprocess.run([
        str(nssm_binary), 'start', prometheus_service_name
    ])

    delay = 15
    print(f'We are giving {delay} seconds for the prometheus service to start properly.')
    time.sleep(delay)

    # Verify proper Prometheus service installation
    service_details = get_service_details(nssm_binary, prometheus_service_name)
    if not service_details:
        print('We could not find the prometheus service we just created. '
            'We cannot continue.')
        return False

    if not (
        service_details['status'] == WINDOWS_SERVICE_RUNNING):

        result = button_dialog(
            title='Prometheus service not running properly',
            text=(
f'''
The prometheus service we just created seems to have issues. Here are some
details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

We cannot proceed if the prometheus service cannot be started properly.
Make sure to check the logs and fix any issue found there. You can see the
logs in:

{prometheus_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        # Stop the service to prevent indefinite restart attempts
        subprocess.run([
            str(nssm_binary), 'stop', prometheus_service_name])

        print(
f'''
To examine your prometheus service logs, inspect the following file:

{prometheus_stderr_log_path}
'''
        )

        return False

    # Iterate over the logs and output them for around 10 seconds
    err_log_read_index = 0
    for i in range(2):
        err_log_text = ''
        with open(prometheus_stderr_log_path, 'r', encoding='utf8') as log_file:
            log_file.seek(err_log_read_index)
            err_log_text = log_file.read()
            err_log_read_index = log_file.tell()

        err_log_length = len(err_log_text)
        if err_log_length > 0:
            print(err_log_text)

        time.sleep(5)

    # Do a simple query on Prometheus to see if it's working properly
    local_prometheus_query_url = 'http://localhost:9090/api/v1/query'
    params = {
        'query': 'promhttp_metric_handler_requests_total',
        'time': datetime.now().timestamp()
    }
    try:
        response = httpx.get(local_prometheus_query_url, params=params)
    except httpx.RequestError as exception:
        result = button_dialog(
            title='Cannot connect to Prometheus',
            text=(
f'''
We could not connect to prometheus server. Here are some details for this
last test we tried to perform:

URL: {local_prometheus_query_url}
Method: GET
Parameters: {json.dumps(params)}
Exception: {exception}

We cannot proceed if the prometheus server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{prometheus_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your prometheus service logs, inspect the following file:

{prometheus_stderr_log_path}
'''
        )

        return False

    if response.status_code != 200:
        result = button_dialog(
            title='Cannot connect to Prometheus',
            text=(
f'''
We could not connect to prometheus server. Here are some details for this
last test we tried to perform:

URL: {local_prometheus_query_url}
Method: GET
Parameters: {json.dumps(params)}
Status code: {response.status_code}

We cannot proceed if the prometheus server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{prometheus_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your prometheus service logs, inspect the following file:

{prometheus_stderr_log_path}
'''
        )

        return False
    
    response_json = response.json()

    retry_index = 0
    retry_count = 5

    while (
        not response_json or
        'status' not in response_json or
        response_json['status'] != 'success'
    ) and retry_index < retry_count:
        result = button_dialog(
            title='Unexpected response from Prometheus',
            text=(
f'''
We received an unexpected response from the prometheus server. Here are
some details for this last test we tried to perform:

URL: {local_prometheus_query_url}
Method: GET
Parameters: {json.dumps(params)}
Response: {json.dumps(response_json)}

We cannot proceed if the prometheus server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{prometheus_stderr_log_path}
'''         ),
            buttons=[
                ('Retry', 1),
                ('Quit', False)
            ]
        ).run()

        if not result:

            print(
f'''
To examine your prometheus service logs, inspect the following file:

{prometheus_stderr_log_path}
'''
            )

            return False
        
        retry_index = retry_index + 1

        # Wait a little before the next retry
        time.sleep(5)

        params = {
        'query': 'promhttp_metric_handler_requests_total',
        'time': datetime.now().timestamp()
        }
        try:
            response = httpx.get(local_prometheus_query_url, params=params)
        except httpx.RequestError as exception:
            result = button_dialog(
                title='Cannot connect to Prometheus',
                text=(
f'''
We could not connect to prometheus server. Here are some details for this
last test we tried to perform:

URL: {local_prometheus_query_url}
Method: GET
Parameters: {json.dumps(params)}
Exception: {exception}

We cannot proceed if the prometheus server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{prometheus_stderr_log_path}
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            print(
f'''
To examine your prometheus service logs, inspect the following file:

{prometheus_stderr_log_path}
'''
            )

            return False

        if response.status_code != 200:
            result = button_dialog(
                title='Cannot connect to Prometheus',
                text=(
f'''
We could not connect to prometheus server. Here are some details for this
last test we tried to perform:

URL: {local_prometheus_query_url}
Method: GET
Parameters: {json.dumps(params)}
Status code: {response.status_code}

We cannot proceed if the prometheus server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{prometheus_stderr_log_path}
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            print(
f'''
To examine your prometheus service logs, inspect the following file:

{prometheus_stderr_log_path}
'''
            )

            return False

        response_json = response.json()

    if (
        not response_json or
        'status' not in response_json or
        response_json['status'] != 'success'
    ):
        # We could not get a proper result from Prometheus after all those retries
        result = button_dialog(
            title='Unexpected response from Prometheus',
            text=(
f'''
After a few retries, we still received an unexpected response from the
prometheus server. Here are some details for this last test we tried to
perform:

URL: {local_prometheus_query_url}
Method: GET
Parameters: {json.dumps(params)}
Response: {json.dumps(response_json)}

We cannot proceed if the prometheus server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{prometheus_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your prometheus service logs, inspect the following file:

{prometheus_stderr_log_path}
'''
        )

        return False

    print(
f'''
Prometheus is installed and working properly.
''' )
    time.sleep(5)

    return True

def install_windows_exporter(base_directory):
    # Install Windows Exporter as a service

    nssm_binary = get_nssm_binary()
    if not nssm_binary:
        return False

    # Check for existing service
    we_service_exists = False
    we_service_name = 'windows_exporter'

    service_details = get_service_details(nssm_binary, we_service_name)

    if service_details is not None:
        we_service_exists = True
    
    if we_service_exists:
        result = button_dialog(
            title='Windows Exporter service found',
            text=(
f'''
The windows exporter service seems to have already been created. Here are
some details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}

Do you want to skip installing windows exporter and its service?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        if result == 1:
            return True
        
        # User wants to proceed, make sure the windows exporter service is stopped first
        subprocess.run([
            str(nssm_binary), 'stop', we_service_name])

    # Check if windows exporter is already installed
    we_found = False
    we_version = 'unknown'
    we_uninstall_command = None

    try:
        we_uninstall_key = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall' + '\\' + WINDOWS_EXPORTER_GUID
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, we_uninstall_key) as key:
            we_found = True

            we_version = winreg.QueryValueEx(key, 'DisplayVersion')
            we_uninstall_command = winreg.QueryValueEx(key, 'UninstallString')
        
        if we_version:
            we_version = we_version[0]
        if we_uninstall_command:
            we_uninstall_command = we_uninstall_command[0]
        
    except OSError as exception:
        we_found = False
    
    install_we = True

    if we_found:
        result = button_dialog(
            title='Windows Exporter found',
            text=(
f'''
Windows exporter seems to have already been installed. Here are some
details found:

Version: {we_version}

Do you want to skip installing windows exporter?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        install_we = (result == 2)

    if install_we:
        # Uninstalling Windows Exporter first if found
        if we_found and we_uninstall_command is not None:
            print('Uninstalling Windows Exporter...')
            process_result = subprocess.run([
                'msiexec', '/x', WINDOWS_EXPORTER_GUID, '/qn'
            ])

            if process_result.returncode != 0:
                print(f'Unexpected return code from msiexec when uninstalling windows exporter. '
                    f'Return code {process_result.returncode}')
                return False
        
        # Getting latest Windows Exporter release files
        we_gh_release_url = GITHUB_REST_API_URL + WINDOWS_EXPORTER_LATEST_RELEASE
        headers = {'Accept': GITHUB_API_VERSION}
        try:
            response = httpx.get(we_gh_release_url, headers=headers)
        except httpx.RequestError as exception:
            print(f'Cannot connect to Github. Exception {exception}')
            return False

        if response.status_code != 200:
            # TODO: Better handling for network response issue
            print(f'Github returned error code. Status code {response.status_code}')
            return False
        
        release_json = response.json()

        if 'assets' not in release_json:
            # TODO: Better handling on unexpected response structure
            print('Unexpected response from Github API.')
            return False
        
        binary_asset = None

        for asset in release_json['assets']:
            if 'name' not in asset:
                continue
            if 'browser_download_url' not in asset:
                continue
        
            file_name = asset['name']
            file_url = asset['browser_download_url']

            if file_name.endswith('amd64.msi'):
                binary_asset = {
                    'file_name': file_name,
                    'file_url': file_url
                }
                break
        
        if binary_asset is None:
            # TODO: Better handling of missing binary in latest release
            print('No windows exporter installer found in Github release')
            return False
        
        # Downloading latest Windows Exporter binary distribution archive
        download_path = base_directory.joinpath('downloads')
        download_path.mkdir(parents=True, exist_ok=True)

        url_file_name = binary_asset['file_name']
        installer_url = binary_asset['file_url']

        we_installer_path = download_path.joinpath(url_file_name)

        try:
            with open(we_installer_path, 'wb') as binary_file:
                print(f'Downloading windows exporter installer {url_file_name}...')
                with httpx.stream('GET', installer_url) as http_stream:
                    if http_stream.status_code != 200:
                        print(f'Cannot download windows exporter installer {installer_url}.\n'
                            f'Unexpected status code {http_stream.status_code}')
                        return False
                    for data in http_stream.iter_bytes():
                        binary_file.write(data)
        except httpx.RequestError as exception:
            print(f'Exception while downloading windows exporter installer. Exception {exception}')
            return False

        # Installing Windows Exporter
        print(f'Installing windows exporter using {url_file_name} ...')
        process_result = subprocess.run([
            'msiexec', '/i', str(we_installer_path), 'ENABLED_COLLECTORS=[defaults],time,process',
            'LISTEN_ADDR=127.0.0.1', '/qn'
        ])

        # Remove download leftovers
        we_installer_path.unlink()

        if process_result.returncode != 0:
            print(f'Unexpected return code from msiexec when installing windows exporter. '
                f'Return code {process_result.returncode}')
            return False

    # Make sure the Windows Exporter service is started
    subprocess.run([
        str(nssm_binary), 'start', we_service_name
    ])

    delay = 15
    print(f'We are giving {delay} seconds for the windows exporter service to start properly.')
    time.sleep(delay)

    # Test Windows Exporter to see if we can read some metrics
    local_we_query_url = 'http://localhost:9182/metrics'
    try:
        response = httpx.get(local_we_query_url)
    except httpx.RequestError as exception:
        result = button_dialog(
            title='Cannot connect to Windows Exporter',
            text=(
f'''
We could not connect to windows exporter server. Here are some details for
this last test we tried to perform:

URL: {local_we_query_url}
Method: GET
Exception: {exception}

We cannot proceed if the windows exporter server is not responding
properly. Make sure to check the logs and fix any issue found there. You
can see the logs in the Event Viewer for Application with source
windows_exporter.
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your windows exporter service logs, inspect logs in the Event
Viewer for Application with source windows_exporter.
'''
        )

        return False

    if response.status_code != 200:
        result = button_dialog(
            title='Cannot connect to Windows Exporter',
            text=(
f'''
We could not connect to windows exporter server. Here are some details for
this last test we tried to perform:

URL: {local_we_query_url}
Method: GET
Status code: {response.status_code}

We cannot proceed if the windows exporter server is not responding
properly. Make sure to check the logs and fix any issue found there. You
can see the logs in the Event Viewer for Application with source
windows_exporter.
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your windows exporter service logs, inspect logs in the Event
Viewer for Application with source windows_exporter.
'''
        )

        return False
    
    # Let's find the number of running processes as a test

    response_text = response.text
    match = re.search(r'windows_os_processes (?P<processes>\d+)', response_text)

    retry_index = 0
    retry_count = 5

    while (
        not match
    ) and retry_index < retry_count:
        result = button_dialog(
            title='Unexpected response from Windows Exporter',
            text=(
f'''
We received an unexpected response from the windows exporter server. Here
are some details for this last test we tried to perform:

URL: {local_we_query_url}
Method: GET
Missing line: windows_os_processes

We cannot proceed if the windows exporter server is not responding
properly. Make sure to check the logs and fix any issue found there. You
can see the logs in the Event Viewer for Application with source
windows_exporter.
'''         ),
            buttons=[
                ('Retry', 1),
                ('Quit', False)
            ]
        ).run()

        if not result:

            print(
f'''
To examine your windows exporter service logs, inspect logs in the Event
Viewer for Application with source windows_exporter.
'''
            )

            return False
        
        retry_index = retry_index + 1

        # Wait a little before the next retry
        time.sleep(5)

        try:
            response = httpx.get(local_we_query_url)
        except httpx.RequestError as exception:
            result = button_dialog(
                title='Cannot connect to Windows Exporter',
                text=(
f'''
We could not connect to windows exporter server. Here are some details for
this last test we tried to perform:

URL: {local_we_query_url}
Method: GET
Exception: {exception}

We cannot proceed if the windows exporter server is not responding
properly. Make sure to check the logs and fix any issue found there. You
can see the logs in the Event Viewer for Application with source
windows_exporter.
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            print(
f'''
To examine your windows exporter service logs, inspect logs in the Event
Viewer for Application with source windows_exporter.
'''
            )

            return False

        if response.status_code != 200:
            result = button_dialog(
                title='Cannot connect to Windows Exporter',
                text=(
f'''
We could not connect to windows exporter server. Here are some details for
this last test we tried to perform:

URL: {local_we_query_url}
Method: GET
Status code: {response.status_code}

We cannot proceed if the windows exporter server is not responding
properly. Make sure to check the logs and fix any issue found there. You
can see the logs in the Event Viewer for Application with source
windows_exporter.
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            print(
f'''
To examine your windows exporter service logs, inspect logs in the Event
Viewer for Application with source windows_exporter.
'''
            )

            return False

        response_text = response.text
        match = re.search(r'windows_os_processes (?P<processes>\d+)', response_text)

    if (
        not match
    ):
        # We could not get a proper result from Windows Exporter after all those retries
        result = button_dialog(
            title='Unexpected response from Windows Exporter',
            text=(
f'''
After a few retries, we still received an unexpected response from the
windows exporter server. Here are some details for this last test we tried
to perform:

URL: {local_we_query_url}
Method: GET
Missing line: windows_os_processes

We cannot proceed if the windows exporter server is not responding
properly. Make sure to check the logs and fix any issue found there. You
can see the logs in the Event Viewer for Application with source
windows_exporter.
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your windows exporter service logs, inspect logs in the Event
Viewer for Application with source windows_exporter.
'''
        )

        return False

    print(
f'''
Windows Exporter is installed and working properly.
''' )
    time.sleep(5)

    return True

def install_grafana(base_directory):
    # Install Grafana as a service

    nssm_binary = get_nssm_binary()
    if not nssm_binary:
        return False

    # Check for existing service
    grafana_service_exists = False
    grafana_service_name = 'grafana'

    service_details = get_service_details(nssm_binary, grafana_service_name)

    if service_details is not None:
        grafana_service_exists = True
    
    if grafana_service_exists:
        result = button_dialog(
            title='Grafana service found',
            text=(
f'''
The grafana service seems to have already been created. Here are some
details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

Do you want to skip installing grafana and its service?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        if result == 1:
            return True
        
        # User wants to proceed, make sure the grafana service is stopped first
        subprocess.run([
            str(nssm_binary), 'stop', grafana_service_name])

    # Check if grafana is already installed
    grafana_path = base_directory.joinpath('bin', 'grafana')
    grafana_bin_path = grafana_path.joinpath('bin')
    grafana_cli_binary_file = grafana_bin_path.joinpath('grafana-cli.exe')
    grafana_server_binary_file = grafana_bin_path.joinpath('grafana-server.exe')

    grafana_found = False
    grafana_version = 'unknown'

    if grafana_cli_binary_file.is_file():
        try:
            process_result = subprocess.run([
                str(grafana_cli_binary_file), '--version'
                ], capture_output=True, text=True)
            grafana_found = True

            process_output = process_result.stdout
            result = re.search(r'version (?P<version>[^ ]+)', process_output)
            if result:
                grafana_version = result.group('version').strip()

        except FileNotFoundError:
            pass
    
    install_grafana_binary = True

    if grafana_found:
        result = button_dialog(
            title='Grafana binary distribution found',
            text=(
f'''
The grafana binary distribution seems to have already been installed.
Here are some details found:

Version: {grafana_version}
Location: {grafana_path}

Do you want to skip installing the grafana binary distribution?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        install_grafana_binary = (result == 2)
    
    if install_grafana_binary:
        # Getting latest Grafana release

        retry_index = 0
        retry_count = 5
        retry_delay = 5

        base_timeout = 10.0
        timeout_retry_increment = 5.0

        response = None

        print('Getting Grafana download packages...')

        while (
            response is None or
            response.status_code != 200
        ) and retry_index < retry_count:
            try:
                timeout_delay = base_timeout + (timeout_retry_increment * retry_index)
                response = httpx.get(GRAFANA_DOWNLOAD_URL, params=GRAFANA_WINDOWS_PARAM, timeout=timeout_delay)
            except httpx.RequestError as exception:
                print(f'Cannot connect to Grafana download page. Exception {exception}.')
                    
                retry_index = retry_index + 1
                if retry_index < retry_count:
                    print(f'We will retry in {retry_delay} seconds.')
                    time.sleep(retry_delay)
                continue

            if response.status_code != 200:
                print(f'Grafana download page returned error code. Status code {response.status_code}')

                retry_index = retry_index + 1
                if retry_index < retry_count:
                    print(f'We will retry in {retry_delay} seconds.')
                    time.sleep(retry_delay)
                continue
        
        if response is None or response.status_code != 200:
            print(f'We could not get the Grafana download packages from the download page after '
                f'a few retries. We cannot continue.')
            return False
        
        response_text = response.text
        soup = BeautifulSoup(response_text, "html.parser")

        results = soup.find_all('div', class_='download-package')

        archive_sha256 = None
        archive_url = None

        for result in results:
            anchors = result.find_all('a')

            for anchor in anchors:
                href = anchor.attrs.get('href', None)
                if href and href.endswith('windows-amd64.zip'):
                    archive_url = href
            
            if archive_url is not None:
                sha_spans = result.find_all('span', class_='download-package__sha', limit=1)
                if sha_spans and len(sha_spans) > 0:
                    sha_text = sha_spans[0].text
                    match = re.search(r'SHA256:\s*(?P<sha256>\S+)', sha_text)
                    if match:
                        archive_sha256 = match.group('sha256')
                break
        
        if archive_url is None:
            # TODO: Better handling of missing binary on website download page
            print('No grafana binary distribution found on grafana download page')
            return False
        
        # Downloading latest Grafana binary distribution archive
        download_path = base_directory.joinpath('downloads')
        download_path.mkdir(parents=True, exist_ok=True)

        url_file_name = urlparse(archive_url).path.split('/')[-1]
        zip_url = archive_url

        grafana_archive_path = download_path.joinpath(url_file_name)
        grafana_archive_hash = hashlib.sha256()
        if grafana_archive_path.is_file():
            grafana_archive_path.unlink()

        try:
            with open(grafana_archive_path, 'wb') as binary_file:
                print(f'Downloading grafana archive {url_file_name}...')
                with httpx.stream('GET', zip_url) as http_stream:
                    if http_stream.status_code != 200:
                        print(f'Cannot download grafana archive {zip_url}.\n'
                            f'Unexpected status code {http_stream.status_code}')
                        return False
                    for data in http_stream.iter_bytes():
                        binary_file.write(data)
                        grafana_archive_hash.update(data)
        except httpx.RequestError as exception:
            print(f'Exception while downloading grafana archive. Exception {exception}')
            return False
        
        # Verify checksum
        if archive_sha256 is not None:
            print('Verifying grafana archive checksum...')
            grafana_archive_hexdigest = grafana_archive_hash.hexdigest()
            if grafana_archive_hexdigest.lower() != archive_sha256.lower():
                print('Grafana archive checksum does not match. We will stop here to protect you.')
                return False

        # Unzip grafana archive
        archive_members = None

        print(f'Extracting grafana archive {url_file_name}...')
        with ZipFile(grafana_archive_path, 'r') as zip_file:
            archive_members = zip_file.namelist()
            zip_file.extractall(download_path)
        
        # Remove download leftovers
        grafana_archive_path.unlink()

        if archive_members is None or len(archive_members) == 0:
            print('No files found in grafana archive. We cannot continue.')
            return False
        
        # Move all those extracted files into their final destination
        if grafana_path.is_dir():
            shutil.rmtree(grafana_path)
        grafana_path.mkdir(parents=True, exist_ok=True)

        archive_extracted_dir = download_path.joinpath(Path(archive_members[0]).parts[0])

        with os.scandir(archive_extracted_dir) as it:
            for diritem in it:
                shutil.move(diritem.path, grafana_path)
            
        # Make sure grafana was installed properly
        grafana_found = False
        if grafana_cli_binary_file.is_file():
            try:
                process_result = subprocess.run([
                    str(grafana_cli_binary_file), '--version'
                    ], capture_output=True, text=True)
                grafana_found = True

                process_output = process_result.stdout
                result = re.search(r'version (?P<version>[^ ]+)', process_output)
                if result:
                    grafana_version = result.group('version').strip()

            except FileNotFoundError:
                pass
        
        if not grafana_server_binary_file.is_file():
            grafana_found = False
    
        if not grafana_found:
            print(f'We could not find the grafana binary distribution from the installed '
                f'archive in {grafana_path}. We cannot continue.')
            return False
        else:
            print(f'Grafana version {grafana_version} installed.')

    # Check if config sample file exists
    grafana_source_config_file = grafana_path.joinpath('conf', 'sample.ini')
    if not grafana_source_config_file.is_file():
        print(f'We could not find the grafana config sample file from the installed '
            f'archive in {grafana_path}. We cannot continue.')
        return False

    # Check if grafana directory already exists
    grafana_datadir = base_directory.joinpath('var', 'lib', 'grafana')
    if grafana_datadir.is_dir():
        grafana_datadir_size = sizeof_fmt(get_dir_size(grafana_datadir))

        result = button_dialog(
            title='Grafana data directory found',
            text=(
f'''
An existing grafana data directory has been found. Here are some details
found:

Location: {grafana_datadir}
Size: {grafana_datadir_size}

Do you want to remove this directory first and start from nothing?
'''         ),
            buttons=[
                ('Remove', 1),
                ('Keep', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        if result == 1:
            shutil.rmtree(grafana_datadir)

    # Setup grafana directory
    grafana_datadir.mkdir(parents=True, exist_ok=True)

    grafana_provisioningdir = grafana_datadir.joinpath('provisioning')
    grafana_provisioningdir.mkdir(parents=True, exist_ok=True)
    
    # Setup datasource provisioning for Prometheus
    grafana_datasourcedir = grafana_provisioningdir.joinpath('datasources')
    grafana_datasourcedir.mkdir(parents=True, exist_ok=True)

    prometheus_datasource_file = grafana_datasourcedir.joinpath('prometheus.yaml')
    with open(prometheus_datasource_file, 'w', encoding='utf8') as datasource_file:
        datasource_file.write(GRAFANA_PROMETHEUS_DATASOURCE)

    # Setup dashboard provisioning for Geth, Teku and Windows Exporter dashboards
    grafana_dashboardprovdir = grafana_provisioningdir.joinpath('dashboards')
    grafana_dashboardprovdir.mkdir(parents=True, exist_ok=True)

    grafana_dashboard_dir = grafana_datadir.joinpath('wizard-dashboards')
    grafana_dashboard_dir.mkdir(parents=True, exist_ok=True)

    grafana_dashboardprov_file = grafana_dashboardprovdir.joinpath('wizard.yaml')
    with open(grafana_dashboardprov_file, 'w', encoding='utf8') as dashboardprov_file:
        dashboardprov_file.write(
f'''
apiVersion: 1

providers:
  # <string> an unique provider name. Required
  - name: 'Wizard Dashboards'
    # <int> Org id. Default to 1
    orgId: 1
    # <string> name of the dashboard folder.
    folder: ''
    # <string> folder UID. will be automatically generated if not specified
    folderUid: ''
    # <string> provider type. Default to 'file'
    type: file
    # <bool> disable dashboard deletion
    disableDeletion: false
    # <int> how often Grafana will scan for changed dashboards
    updateIntervalSeconds: 60
    # <bool> allow updating provisioned dashboards from the UI
    allowUiUpdates: true
    options:
      # <string, required> path to dashboard files on disk. Required when using the 'file' type
      path: {grafana_dashboard_dir}
      # <bool> use folder names from filesystem to create folders in Grafana
      foldersFromFilesStructure: true
'''
        )
    
    geth_dashboard_file = grafana_dashboard_dir.joinpath('geth.json')
    with open(geth_dashboard_file, 'w', encoding='utf8') as dashboard_file:
        dashboard_file.write(GETH_GRAFANA_DASHBOARD)
    
    windows_system_dashboard_file = grafana_dashboard_dir.joinpath('windows-system.json')
    with open(windows_system_dashboard_file, 'w', encoding='utf8') as dashboard_file:
        dashboard_file.write(WINDOWS_SYSTEM_OVERVIEW_GRAFANA_DASHBOARD)
    
    windows_services_dashboard_file = grafana_dashboard_dir.joinpath('windows-services.json')
    with open(windows_services_dashboard_file, 'w', encoding='utf8') as dashboard_file:
        dashboard_file.write(WINDOWS_SERVICES_PROCESSES_GRAFANA_DASHBOARD)
    
    teku_dashboard_file = grafana_dashboard_dir.joinpath('teku.json')
    with open(teku_dashboard_file, 'w', encoding='utf8') as dashboard_file:
        dashboard_file.write(TEKU_GRAFANA_DASHBOARD)
    
    home_dashboard_file = grafana_dashboard_dir.joinpath('home.json')
    with open(home_dashboard_file, 'w', encoding='utf8') as dashboard_file:
        dashboard_file.write(HOME_GRAFANA_DASHBOARD)

    # Create grafana custom config file
    sample_config_content = None

    chunk_size = 1024 * 64

    with open(str(grafana_source_config_file), 'r', encoding='utf8') as sample_file:
        content_stream = io.StringIO()
        for chunk in iter(partial(sample_file.read, chunk_size), ''):
            content_stream.write(chunk)
        sample_config_content = content_stream.getvalue()
        content_stream.close()
    
    if sample_config_content is None or sample_config_content == '':
        print(f'We could not get the content of the grafana config sample file from the installed '
            f'archive in {grafana_path}. We cannot continue.')
        return False
    
    custom_config_content = sample_config_content
    custom_config_content = re.sub(
        r';http_addr =.*',
        'http_addr = 127.0.0.1',
        custom_config_content)
    custom_config_content = re.sub(
        r';data =.*',
        f'data = {re_repl_escape(str(grafana_datadir))}',
        custom_config_content)

    grafana_logsdir = grafana_datadir.joinpath('logs')
    grafana_logsdir.mkdir(parents=True, exist_ok=True)

    custom_config_content = re.sub(
        r';logs =.*',
        f'logs = {re_repl_escape(str(grafana_logsdir))}',
        custom_config_content)

    custom_config_content = re.sub(
        r';provisioning =.*',
        f'provisioning = {re_repl_escape(str(grafana_provisioningdir))}',
        custom_config_content)
    
    custom_config_content = re.sub(
        r';default_home_dashboard_path =.*',
        f'default_home_dashboard_path = {re_repl_escape(str(home_dashboard_file))}',
        custom_config_content)

    # Setup grafana custom config file
    grafana_config_path = base_directory.joinpath('etc', 'grafana')
    if not grafana_config_path.is_dir():
        grafana_config_path.mkdir(parents=True, exist_ok=True)
    
    grafana_config_file = grafana_config_path.joinpath('grafana.ini')
    if grafana_config_file.is_file():
        grafana_config_file.unlink()

    with open(str(grafana_config_file), 'w', encoding='utf8') as config_file:
        config_file.write(custom_config_content)

    # Install required plugins
    print('Installing required plugins for Grafana...')
    process_result = subprocess.run([
        str(grafana_cli_binary_file), 'plugins', 'install', 'flant-statusmap-panel'
    ], cwd=str(grafana_bin_path))

    # Setup grafana service
    log_path = base_directory.joinpath('var', 'log')
    log_path.mkdir(parents=True, exist_ok=True)

    grafana_stdout_log_path = log_path.joinpath('grafana-service-stdout.log')
    grafana_stderr_log_path = log_path.joinpath('grafana-service-stderr.log')

    if grafana_stdout_log_path.is_file():
        grafana_stdout_log_path.unlink()
    if grafana_stderr_log_path.is_file():
        grafana_stderr_log_path.unlink()

    grafana_arguments = [
        '-config', str(grafana_config_file)
    ]

    parameters = {
        'DisplayName': GRAFANA_SERVICE_DISPLAY_NAME,
        'AppRotateFiles': '1',
        'AppRotateSeconds': '86400',
        'AppRotateBytes': '10485760',
        'AppStdout': str(grafana_stdout_log_path),
        'AppStderr': str(grafana_stderr_log_path)
    }

    if not create_service(nssm_binary, grafana_service_name, grafana_server_binary_file,
        grafana_arguments, parameters):
        print('There was an issue creating the grafana service. We cannot continue.')
        return False

    print('Starting grafana service...')
    process_result = subprocess.run([
        str(nssm_binary), 'start', grafana_service_name
    ])

    delay = 15
    print(f'We are giving {delay} seconds for the grafana service to start properly.')
    time.sleep(delay)

    # Verify proper Grafana service installation
    service_details = get_service_details(nssm_binary, grafana_service_name)
    if not service_details:
        print('We could not find the grafana service we just created. '
            'We cannot continue.')
        return False

    if not (
        service_details['status'] == WINDOWS_SERVICE_RUNNING):

        result = button_dialog(
            title='Grafana service not running properly',
            text=(
f'''
The grafana service we just created seems to have issues. Here are some
details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

We cannot proceed if the grafana service cannot be started properly.
Make sure to check the logs and fix any issue found there. You can see the
logs in:

{grafana_stdout_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        # Stop the service to prevent indefinite restart attempts
        subprocess.run([
            str(nssm_binary), 'stop', grafana_service_name])

        print(
f'''
To examine your grafana service logs, inspect the following file:

{grafana_stdout_log_path}
'''
        )

        return False

    # Iterate over the logs and output them for around 10 seconds
    err_log_read_index = 0
    for i in range(2):
        err_log_text = ''
        with open(grafana_stdout_log_path, 'r', encoding='utf8') as log_file:
            log_file.seek(err_log_read_index)
            err_log_text = log_file.read()
            err_log_read_index = log_file.tell()

        err_log_length = len(err_log_text)
        if err_log_length > 0:
            print(err_log_text)

        time.sleep(5)

    # Test if Grafana is working properly
    local_grafana_url = 'http://localhost:3000/login'
    try:
        response = httpx.get(local_grafana_url)
    except httpx.RequestError as exception:
        result = button_dialog(
            title='Cannot connect to Grafana',
            text=(
f'''
We could not connect to the grafana server. Here are some details for
this last test we tried to perform:

URL: {local_grafana_url}
Method: GET
Exception: {exception}

We cannot proceed if the grafana server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{grafana_stdout_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your grafana service logs, inspect the following file:

{grafana_stdout_log_path}
'''
        )

        return False

    if response.status_code != 200:
        result = button_dialog(
            title='Cannot connect to Grafana',
            text=(
f'''
We could not connect to the grafana server. Here are some details for
this last test we tried to perform:

URL: {local_grafana_url}
Method: GET
Status code: {response.status_code}

We cannot proceed if the grafana server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{grafana_stdout_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your grafana service logs, inspect the following file:

{grafana_stdout_log_path}
'''
        )

        return False
    
    print(
f'''
Grafana is installed and working properly.
''' )
    time.sleep(5)
    
    return True

def re_repl_escape(value):
    return value.replace('\\', '\\\\')

def get_dir_size(directory):
    total_size = 0
    directories = []
    directories.append(directory)

    while len(directories) > 0:
        next_dir = directories.pop()
        with os.scandir(next_dir) as it:
            for item in it:
                if item.is_file():
                    total_size += item.stat().st_size
                elif item.is_dir():
                    directories.append(item.path)
    
    return total_size

def sizeof_fmt(num, suffix='B'):
    if num == 0:
        return 'Empty'
    for unit in ['','Ki','Mi','Gi','Ti','Pi','Ei','Zi']:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, 'Yi', suffix)
