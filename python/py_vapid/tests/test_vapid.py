import binascii
import base64
import os
import json
import unittest
from nose.tools import eq_, ok_
from mock import patch, Mock

from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives import hashes

from py_vapid import Vapid01, Vapid02, VapidException
from py_vapid.jwt import decode
from py_vapid.utils import b64urldecode

# This is a private key in DER form.
T_DER = """
MHcCAQEEIPeN1iAipHbt8+/KZ2NIF8NeN24jqAmnMLFZEMocY8RboAoGCCqGSM49
AwEHoUQDQgAEEJwJZq/GN8jJbo1GGpyU70hmP2hbWAUpQFKDByKB81yldJ9GTklB
M5xqEwuPM7VuQcyiLDhvovthPIXx+gsQRQ==
"""

key = dict(
    d=111971876876285331364078054667935803036831194031221090723024134705696601261147,  # noqa
    x=7512698603580564493364310058109115206932767156853859985379597995200661812060,  # noqa
    y=74837673548863147047276043384733294240255217876718360423043754089982135570501  # noqa
)

# This is the same private key, in PEM form.
T_PRIVATE = ("-----BEGIN PRIVATE KEY-----{}"
             "-----END PRIVATE KEY-----\n").format(T_DER)

# This is the same private key, as a point in uncompressed form. This should
# be Base64url-encoded without padding.
T_RAW = """
943WICKkdu3z78pnY0gXw143biOoCacwsVkQyhxjxFs
""".strip().encode('utf8')

# This is a public key in PEM form.
T_PUBLIC = """-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEEJwJZq/GN8jJbo1GGpyU70hmP2hb
WAUpQFKDByKB81yldJ9GTklBM5xqEwuPM7VuQcyiLDhvovthPIXx+gsQRQ==
-----END PUBLIC KEY-----
"""

# this is a public key in uncompressed form ('\x04' + 2 * 32 octets)
# Remember, this should have any padding stripped.
T_PUBLIC_RAW = (
    "BBCcCWavxjfIyW6NRhqclO9IZj9oW1gFKUBSgwcigfNc"
    "pXSfRk5JQTOcahMLjzO1bkHMoiw4b6L7YTyF8foLEEU"
    ).strip('=').encode('utf8')


def setUp(self):
    with open('/tmp/private', 'w') as ff:
        ff.write(T_PRIVATE)
    with open('/tmp/public', 'w') as ff:
        ff.write(T_PUBLIC)
    with open('/tmp/private.der', 'w') as ff:
        ff.write(T_DER)


def tearDown(self):
    os.unlink('/tmp/private')
    os.unlink('/tmp/public')


class VapidTestCase(unittest.TestCase):
    def check_keys(self, v):
        eq_(v.private_key.private_numbers().private_value, key.get('d'))
        eq_(v.public_key.public_numbers().x, key.get('x'))
        eq_(v.public_key.public_numbers().y, key.get('y'))

    def test_init(self):
        v1 = Vapid01.from_file("/tmp/private")
        self.check_keys(v1)
        v2 = Vapid01.from_pem(T_PRIVATE.encode())
        self.check_keys(v2)
        v3 = Vapid01.from_der(T_DER.encode())
        self.check_keys(v3)
        v4 = Vapid01.from_file("/tmp/private.der")
        self.check_keys(v4)
        no_exist = '/tmp/not_exist'
        Vapid01.from_file(no_exist)
        ok_(os.path.isfile(no_exist))
        os.unlink(no_exist)

    def repad(self, data):
        return data + "===="[len(data) % 4:]

    @patch("py_vapid.Vapid01.from_pem", side_effect=Exception)
    def test_init_bad_read(self, mm):
        self.assertRaises(Exception,
                          Vapid01.from_file,
                          private_key_file="/tmp/private")

    def test_gen_key(self):
        v = Vapid01()
        v.generate_keys()
        ok_(v.public_key)
        ok_(v.private_key)

    def test_private_key(self):
        v = Vapid01()
        self.assertRaises(VapidException,
                          lambda: v.private_key)

    def test_public_key(self):
        v = Vapid01()
        eq_(v._private_key, None)
        eq_(v._public_key, None)

    def test_save_key(self):
        v = Vapid01()
        v.generate_keys()
        v.save_key("/tmp/p2")
        os.unlink("/tmp/p2")

    def test_same_public_key(self):
        v = Vapid01()
        v.generate_keys()
        v.save_public_key("/tmp/p2")
        os.unlink("/tmp/p2")

    def test_from_raw(self):
        v = Vapid01.from_raw(T_RAW)
        self.check_keys(v)

    def test_validate(self):
        v = Vapid01.from_file("/tmp/private")
        msg = "foobar".encode('utf8')
        vtoken = v.validate(msg)
        ok_(v.public_key.verify(
            base64.urlsafe_b64decode(self.repad(vtoken).encode()),
            msg,
            ec.ECDSA(hashes.SHA256())))
        # test verify
        ok_(v.verify_token(msg, vtoken))

    def test_sign_01(self):
        v = Vapid01.from_file("/tmp/private")
        claims = {"aud": "https://example.com",
                  "sub": "mailto:admin@example.com"}
        result = v.sign(claims, "id=previous")
        eq_(result['Crypto-Key'],
            'id=previous;p256ecdsa=' + T_PUBLIC_RAW.decode('utf8'))
        pkey = binascii.b2a_base64(
            v.public_key.public_numbers().encode_point()
        ).decode('utf8').replace('+', '-').replace('/', '_').strip()
        items = decode(result['Authorization'].split(' ')[1], pkey)
        eq_(items, claims)
        result = v.sign(claims)
        eq_(result['Crypto-Key'],
            'p256ecdsa=' + T_PUBLIC_RAW.decode('utf8'))

    def test_sign_02(self):
        v = Vapid02.from_file("/tmp/private")
        claims = {"aud": "https://example.com",
                  "sub": "mailto:admin@example.com",
                  "foo": "extra value"}
        result = v.sign(claims, "id=previous")
        auth = result['Authorization']
        eq_(auth[:6], 'vapid ')
        ok_(' t=' in auth)
        ok_(',k=' in auth)
        parts = auth[6:].split(',')
        eq_(len(parts), 2)
        t_val = json.loads(base64.urlsafe_b64decode(
            self.repad(parts[0][2:].split('.')[1])
        ).decode('utf8'))
        k_val = binascii.a2b_base64(self.repad(parts[1][2:]))
        eq_(binascii.hexlify(k_val)[:2], b'04')
        eq_(len(k_val), 65)
        for k in claims:
            eq_(t_val[k], claims[k])

    def test_alt_sign(self):
        """ecdsa uses a raw key pair to sign, openssl uses a DER."""
        v = Vapid01.from_file("/tmp/private")
        claims = {"aud": "https://example.com",
                  "sub": "mailto:admin@example.com",
                  "foo": "extra value"}
        # Get a signed token.
        result = v.sign(claims)
        # Convert the dss into raw.
        auth, sig = result.get('Authorization').split(' ')[1].rsplit('.', 1)
        ss = utils.decode_dss_signature(b64urldecode(sig.encode('utf8')))
        new_sig = binascii.b2a_base64(
            binascii.unhexlify("%064x%064x" % ss)
        ).strip().strip(b'=').decode()
        new_auth = auth + '.' + new_sig
        # phew, all that done, now check
        pkey = result.get("Crypto-Key").split('=')[1]
        items = decode(new_auth, pkey)

        eq_(items, claims)

    def test_bad_sign(self):
        v = Vapid01.from_file("/tmp/private")
        self.assertRaises(VapidException,
                          v.sign,
                          {})
        self.assertRaises(VapidException,
                          v.sign,
                          {'sub': 'foo',
                           'aud': "p.example.com"})
        self.assertRaises(VapidException,
                          v.sign,
                          {'sub': 'mailto:foo@bar.com',
                           'aud': "p.example.com"})
        self.assertRaises(VapidException,
                          v.sign,
                          {'sub': 'mailto:foo@bar.com',
                              'aud': "https://p.example.com:8080/"})

    @patch('cryptography.hazmat.primitives.asymmetric'
           '.ec.EllipticCurvePublicNumbers')
    def test_invalid_sig(self, mm):
        from cryptography.exceptions import InvalidSignature
        ve = Mock()
        ve.verify.side_effect = InvalidSignature
        pk = Mock()
        pk.public_key.return_value = ve
        mm.from_encoded_point.return_value = pk
        self.assertRaises(InvalidSignature,
                          decode,
                          'foo.bar.blat',
                          'aaaa')
        self.assertRaises(InvalidSignature,
                          decode,
                          'foo.bar.a',
                          'aaaa')
