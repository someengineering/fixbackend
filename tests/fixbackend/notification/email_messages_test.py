#  Copyright (c) 2024. Some Engineering
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
from fixbackend.notification.email.email_messages import get_env


def test_readable_number() -> None:
    assert get_env().from_string("{{ 0|readable_number }}").render() == "0"
    assert get_env().from_string("{{ 1|readable_number }}").render() == "1"
    assert get_env().from_string("{{ 2|readable_number }}").render() == "2"
    assert get_env().from_string("{{ 3|readable_number }}").render() == "3"
    assert get_env().from_string("{{ 4|readable_number }}").render() == "4"
    assert get_env().from_string("{{ -3|readable_number }}").render() == "-3"
    assert get_env().from_string("{{ 1000|readable_number }}").render() == "1 K"
    assert get_env().from_string("{{ 1000000|readable_number }}").render() == "1 M"
    assert get_env().from_string("{{ 1000000|readable_number(with_sign=true) }}").render() == "+1 M"
    assert get_env().from_string("{{ -1000000|readable_number }}").render() == "-1 M"


def test_pluralize() -> None:
    assert get_env().from_string("{{ 'word'|pluralize(1) }}").render() == "1 word"
    assert get_env().from_string("{{ 'word'|pluralize(2) }}").render() == "2 words"
    assert get_env().from_string("{{ 'word'|pluralize(23) }}").render() == "23 words"
    assert get_env().from_string("{{ 'word'|pluralize(-2) }}").render() == "-2 words"


def test_readable_bytes() -> None:
    assert get_env().from_string("{{ 1024|readable_bytes }}").render() == "1 KiB"
    assert get_env().from_string("{{ 4348576|readable_bytes }}").render() == "4 MiB"
    assert get_env().from_string("{{ -4348576|readable_bytes }}").render() == "-4 MiB"
    assert get_env().from_string("{{ 3214348576|readable_bytes }}").render() == "2 GiB"
    assert get_env().from_string("{{ 233214348576|readable_bytes }}").render() == "217 GiB"
    assert get_env().from_string("{{ 233214348576|readable_bytes(with_sign=true) }}").render() == "+217 GiB"
    assert get_env().from_string("{{ -233214348576|readable_bytes(with_sign=true) }}").render() == "-217 GiB"
