Rebounds: regular expression bounds
===================================

Determines whether a string is a lexicographic lower/upper bound on the
language matched by a regular expression.

    ./rebounds.py <string> <regex>

Examples:

    $ ./rebounds.py abc abcd
    lower:  True
    upper:  False

    $ ./rebounds.py abc abacd
    lower:  False
    upper:  True

    $ ./rebounds.py abcd abcd
    lower:  False
    upper:  False

    $ ./rebounds.py abcd abc
    lower:  False
    upper:  True

    $ ./rebounds.py ab abc
    lower:  True
    upper:  False
 
    $ ./rebounds.py ab 'a*bc'
    lower:  False
    upper:  False

    $ ./rebounds.py ab abc?
    lower:  False
    upper:  False

    $ ./rebounds.py zig 'foo|(ba[rz])*|zag'
    lower:  False
    upper:  True

    $ ./rebounds.py quux 'foo|(ba[rz])*|zag'
    lower:  False
    upper:  False

    $ ./rebounds.py bam 'foo|(ba[rz])*|zag'
    lower:  True
    upper:  False
