from distutils.core import setup

description = '''Wrapper around TDT's ActiveX library'''

setup(
    name='TDTPy',
    version='0.7',
    author='Brad Buran',
    author_email='bburan@alum.mit.edu',
    packages=['tdt'],
    url='http://bradburan.com/programs-and-scripts',
    license='LICENSE.txt',
    description='Module for communicating with TDT\'s System 3 hardware',
)