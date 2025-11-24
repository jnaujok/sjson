# Streaming JSON Library

[![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![PyPI Version](https://img.shields.io/pypi/v/sjson.svg)](https://pypi.org/project/sjson/)
[![License](https://img.shields.io/pypi/l/sjson.svg)](https://pypi.org/project/sjson/)

This library is meant to compress JSON into a binary representation that is likely as compressed as possible without prior knowledge of the library. 

## Current State
Currently still in a pre-alpha state, the library can compress a JSON dictionary into a tight binary representation, with the caveat that currently the dictionary of names is not yet transferred to a listening party. 

To truly use this library, there must be an "ACK/NAK" mechanism over the top of it, where the receiver can NAK a message with a request for library fields in return. The library fields will then be sent (LZ4 compressed) to the receiver where they can build a sender dictionary.

Since this is a totally dynamic protocol, each receiver will need a dictionary stored for each sender. 
