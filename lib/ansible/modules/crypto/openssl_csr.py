#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# (c) 2017, Yanis Guenane <yanis+ansible@guenane.org>
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

ANSIBLE_METADATA = {'metadata_version': '1.0',
                    'status': ['preview'],
                    'supported_by': 'community'}


DOCUMENTATION = '''
---
module: openssl_csr
author: "Yanis Guenane (@Spredzy)"
version_added: "2.4"
short_description: Generate OpenSSL Certificate Signing Request (CSR)
description:
    - "This module allows one to (re)generates OpenSSL certificate signing requests.
       It uses the pyOpenSSL (>= 0.15) python library to interact with openssl. This module support
       the subjectAltName extension. Note: At least one of commonName or subjectAltName must
       be specified."
requirements:
    - "python-pyOpenSSL (>= 0.15)"
options:
    state:
        required: false
        default: "present"
        choices: [ present, absent ]
        description:
            - Whether the certificate signing request should exist or not, taking action if the state is different from what is stated.
    digest:
        required: false
        default: "sha256"
        description:
            - Digest used when signing the certificate signing request with the private key
    privatekey_path:
        required: true
        description:
            - Path to the privatekey to use when signing the certificate signing request
    version:
        required: false
        default: 3
        description:
            - Version of the certificate signing request
    force:
        required: false
        default: False
        choices: [ True, False ]
        description:
            - Should the certificate signing request be forced regenerated by this ansible module
    path:
        required: true
        description:
            - Name of the folder in which the generated OpenSSL certificate signing request will be written
    subjectAltName:
        required: false
        description:
            - SAN extention to attach to the certificate signing request
    countryName:
        required: false
        aliases: [ 'C' ]
        description:
            - countryName field of the certificate signing request subject
    stateOrProvinceName:
        required: false
        aliases: [ 'ST' ]
        description:
            - stateOrProvinceName field of the certificate signing request subject
    localityName:
        required: false
        aliases: [ 'L' ]
        description:
            - localityName field of the certificate signing request subject
    organizationName:
        required: false
        aliases: [ 'O' ]
        description:
            - organizationName field of the certificate signing request subject
    organizationUnitName:
        required: false
        aliases: [ 'OU' ]
        description:
            - organizationUnitName field of the certificate signing request subject
    commonName:
        required: false
        aliases: [ 'CN' ]
        description:
            - commonName field of the certificate signing request subject
    emailAddress:
        required: false
        aliases: [ 'E' ]
        description:
            - emailAddress field of the certificate signing request subject
'''


EXAMPLES = '''
# Generate an OpenSSL Certificate Signing Request
- openssl_csr:
    path: /etc/ssl/csr/www.ansible.com.csr
    privatekey_path: /etc/ssl/private/ansible.com.pem
    commonName: www.ansible.com

# Generate an OpenSSL Certificate Signing Request with Subject informations
- openssl_csr:
    path: /etc/ssl/csr/www.ansible.com.csr
    privatekey_path: /etc/ssl/private/ansible.com.pem
    countryName: FR
    organizationName: Ansible
    emailAddress: jdoe@ansible.com
    commonName: www.ansible.com

# Generate an OpenSSL Certificate Signing Request with subjectAltName extension
- openssl_csr:
    path: /etc/ssl/csr/www.ansible.com.csr
    privatekey_path: /etc/ssl/private/ansible.com.pem
    subjectAltName: 'DNS:www.ansible.com,DNS:m.ansible.com'

# Force re-generate an OpenSSL Certificate Signing Request
- openssl_csr:
    path: /etc/ssl/csr/www.ansible.com.csr
    privatekey_path: /etc/ssl/private/ansible.com.pem
    force: True
    commonName: www.ansible.com
'''


RETURN = '''
csr:
    description: Path to the generated Certificate Signing Request
    returned: changed or success
    type: string
    sample: /etc/ssl/csr/www.ansible.com.csr
subject:
    description: A dictionnary of the subject attached to the CSR
    returned: changed or success
    type: list
    sample: {'CN': 'www.ansible.com', 'O': 'Ansible'}
subjectAltName:
    description: The alternative names this CSR is valid for
    returned: changed or success
    type: string
    sample: 'DNS:www.ansible.com,DNS:m.ansible.com'
'''

import errno
import os

try:
    from OpenSSL import crypto
    from OpenSSL.crypto import load_certificate_request, FILETYPE_PEM
except ImportError:
    pyopenssl_found = False
else:
    pyopenssl_found = True

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.pycompat24 import get_exception


class CertificateSigningRequestError(Exception):
    pass


class CertificateSigningRequest(object):

    def __init__(self, module):
        self.state = module.params['state']
        self.digest = module.params['digest']
        self.force = module.params['force']
        self.subjectAltName = module.params['subjectAltName']
        self.path = module.params['path']
        self.privatekey_path = module.params['privatekey_path']
        self.version = module.params['version']
        self.changed = True
        self.request = None
        self.privatekey = None

        self.subject = {
            'C': module.params['countryName'],
            'ST': module.params['stateOrProvinceName'],
            'L': module.params['localityName'],
            'O': module.params['organizationName'],
            'OU': module.params['organizationalUnitName'],
            'CN': module.params['commonName'],
            'emailAddress': module.params['emailAddress'],
        }

        if self.subjectAltName:
            self.subjectAltName = self.subjectAltName.replace(' ', '').split(',')
            if 'DNS:%s' % self.subject['CN'] not in self.subjectAltName:
                self.subjectAltName.insert(0, 'DNS:%s' % self.subject['CN'])

        for (key, value) in self.subject.items():
            if value is None:
                del self.subject[key]

    def check_diff(self):
        if os.path.exists(self.path) and not self.force:
            current_csr_content = open(self.path).read()
            current_csr_req = load_certificate_request(FILETYPE_PEM, current_csr_content)
            current_csr_subject = current_csr_req.get_subject()
            current_csr_components = dict(current_csr_subject.get_components())
            current_csr_extensions = current_csr_req.get_extensions()
            for (element_name, element_value) in self.subject.items():
                if element_name in current_csr_components and element_value != current_csr_components[element_name]:
                    return True

            if not current_csr_extensions:
                if self.subjectAltName:
                    return True
                return False

            current_subject_alt_name = next(extension for extension in current_csr_extensions if extension.get_short_name() == 'subjectAltName')
            current_subject_alt_name = current_subject_alt_name.__str__().replace(' ', '').split(',')
            subject_alt_name = self.subjectAltName
            if len(current_subject_alt_name) != len(subject_alt_name):
                return True

            for alt_name in subject_alt_name:
                if alt_name not in current_subject_alt_name:
                    return True

        return False

    def generate(self, module):
        '''Generate the certificate signing request.'''

        diff_found = self.check_diff()

        if not os.path.exists(self.path) or self.force or diff_found:
            req = crypto.X509Req()
            req.set_version(self.version)
            subject = req.get_subject()
            for (key, value) in self.subject.items():
                if value is not None:
                    setattr(subject, key, value)

            if self.subjectAltName:
                req.add_extensions([crypto.X509Extension("subjectAltName", False, ','.join(self.subjectAltName))])

            privatekey_content = open(self.privatekey_path).read()
            self.privatekey = crypto.load_privatekey(crypto.FILETYPE_PEM, privatekey_content)

            req.set_pubkey(self.privatekey)
            req.sign(self.privatekey, self.digest)
            self.request = req

            try:
                csr_file = open(self.path, 'w')
                csr_file.write(crypto.dump_certificate_request(crypto.FILETYPE_PEM, self.request))
                csr_file.close()
            except (IOError, OSError):
                e = get_exception()
                raise CertificateSigningRequestError(e)
        else:
            self.changed = False

        file_args = module.load_file_common_arguments(module.params)
        if module.set_fs_attributes_if_different(file_args, False):
            self.changed = True

    def remove(self):
        '''Remove the Certificate Signing Request.'''

        try:
            os.remove(self.path)
        except OSError:
            e = get_exception()
            if e.errno != errno.ENOENT:
                raise CertificateSigningRequestError(e)
            else:
                self.changed = False

    def dump(self):
        '''Serialize the object into a dictionnary.'''

        result = {
            'csr': self.path,
            'subject': self.subject,
            'subjectAltName': ','.join(self.subjectAltName),
            'changed': self.changed
        }

        return result


def main():
    module = AnsibleModule(
        argument_spec=dict(
            state=dict(default='present', choices=['present', 'absent'], type='str'),
            digest=dict(default='sha256', type='str'),
            privatekey_path=dict(require=True, type='path'),
            version=dict(default='3', type='int'),
            force=dict(default=False, type='bool'),
            subjectAltName=dict(aliases=['subjectAltName'], type='str'),
            path=dict(required=True, type='path'),
            countryName=dict(aliases=['C'], type='str'),
            stateOrProvinceName=dict(aliases=['ST'], type='str'),
            localityName=dict(aliases=['L'], type='str'),
            organizationName=dict(aliases=['O'], type='str'),
            organizationalUnitName=dict(aliases=['OU'], type='str'),
            commonName=dict(aliases=['CN'], type='str'),
            emailAddress=dict(aliases=['E'], type='str'),
        ),
        add_file_common_args=True,
        supports_check_mode=True,
        required_one_of=[['commonName', 'subjectAltName']],
    )

    path = module.params['path']
    base_dir = os.path.dirname(module.params['path'])

    if not os.path.isdir(base_dir):
        module.fail_json(name=path, msg='The directory %s does not exist' % path)

    csr = CertificateSigningRequest(module)

    if module.params['state'] == 'present':

        if module.check_mode:
            result = csr.dump()
            diff_found = csr.check_diff()
            result['changed'] = module.params['force'] or not os.path.exists(path) or diff_found
            module.exit_json(**result)

        try:
            csr.generate(module)
        except CertificateSigningRequestError:
            e = get_exception()
            module.fail_json(msg=str(e))

    else:

        if module.check_mode:
            result = csr.dump()
            result['changed'] = os.path.exists(path)
            module.exit_json(**result)

        try:
            csr.remove()
        except CertificateSigningRequestError:
            e = get_exception()
            module.fail_json(msg=str(e))

    result = csr.dump()

    module.exit_json(**result)


if __name__ == "__main__":
    main()
