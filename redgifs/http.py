"""
The MIT License (MIT)

Copyright (c) 2022-present scrazzz

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the "Software"),
to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
"""

from __future__ import annotations

import io
import os
import re
import sys
import logging
from urllib.parse import quote
from typing import Any, ClassVar, Dict, List, NamedTuple, Optional, Union

import requests
import aiohttp
import yarl

from . import __version__
from .errors import HTTPException
from .enums import Tags, Order
from .const import REDGIFS_THUMBS_RE

_log = logging.getLogger(__name__)

class Route:
    BASE: ClassVar[str] = "https://api.redgifs.com"

    def __init__(self, method: str, path: str, **parameters: Any) -> None:
        self.method: str = method
        self.path: str = path
        url: str = self.BASE + self.path
        if parameters:
            url = url.format_map({k: quote(v) if isinstance(v, str) else v for k, v in parameters.items()})
        self.url: str = url

class ProxyAuth(NamedTuple):
    """
    username: :class:`str`
        The username.
    password: :class:`str`
        The password.
    """
    username: str
    password: str

class HTTP:
    def __init__(
        self,
        session: Optional[requests.Session] = None,
        *,
        proxy: Optional[str] = None,
        proxy_auth: Optional[ProxyAuth] = None
    ) -> None:

        if session is not None and not isinstance(session, requests.Session):
            raise RuntimeError("session is not of type requests.Session")

        self.__session: requests.Session = session or requests.Session()
        self.headers: Dict[str, str] = {
            'User-Agent': f'redgifs (https://github.com/scrazzz/redgifs {__version__}) Python/{sys.version[:3]}'
        }
        self.proxy: Optional[yarl.URL] = yarl.URL(proxy) if proxy else None
        self.proxy_auth: Optional[ProxyAuth] = proxy_auth

        # Set proxy
        if self.proxy:
            self._proxy = {self.proxy.scheme: str(self.proxy)}
        else:
            self._proxy = None

        # Set proxy auth
        if self.proxy_auth and self._proxy:
            self._proxy_auth = (self.proxy_auth.username, self.proxy_auth.password)
        # Don't set proxy authorization if no proxy URL given (self._proxy)
        else:
            self._proxy_auth = None

    def request(self, route: Route, **kwargs: Any) -> Any:
        url: str = route.url
        method: str = route.method
        r: requests.Response = self.__session.request(
            method, url, headers=self.headers, proxies=self._proxy, auth=self._proxy_auth, timeout=60.0, **kwargs
        )
        _log.debug(f'{method} {url} returned code: {r.status_code}')
        js = r.json()
        if r.status_code == 200:
            _log.debug(f'{method} {url} received: {js}')
            return js
        else:
            raise HTTPException(r, js)

    def close(self) -> None:
        self.__session.close()

    # GIF methods

    def get_tags(self, **params: Any):
        return self.request(Route('GET', '/v1/tags'))

    def get_gif(self, id: str, **params: Any):
        r = Route('GET', '/v2/gifs/{id}', id=id)
        return self.request(r, **params)

    def search(self, search_text: Union[str, Tags], order: Order, count: int, page: int, **params: Any):
        r = Route(
            'GET', '/v2/gifs/search?search_text={search_text}&order={order}&count={count}&page={page}',
            search_text=search_text, order=order.value, count=count, page=page
        )
        return self.request(r, **params)

    def search_creators(
        self,
        page: int,
        order: Order,
        verified: bool,
        tags: Optional[Union[List[Tags], List[str]]],
        **params: Any
    ):
        if tags:
            r = Route(
                'GET', '/v1/creators/search?page={page}&order={order}&verified={verified}&tags={tags}',
                page=page, order=order.value, verified=verified,
                tags=','.join(t.value for t in tags) if isinstance(tags[0], Tags) else ','.join(t for t in tags) # type: ignore
            )
        else:
            r = Route(
                'GET', '/v1/creators/search?page={page}&order={order}&verified={verified}',
                page=page, order=order.value, verified=verified
            )
        return self.request(r, **params)

    # Pic methods

    def search_image(self, search_text: Union[str, Tags], order: Order, count: int, page: int, **params: Any):
        r = Route(
            'GET', '/v2/gifs/search?search_text={search_text}&order={order}&count={count}&page={page}&type=i',
            search_text=search_text, order=order.value, count=count, page=page
        )
        return self.request(r, **params)
    
    # download

    def download(self, url: str, fp: Union[str, bytes, os.PathLike[Any], io.BufferedIOBase]) -> int:
        """A friendly method to download a RedGifs media."""

        yarl_url = yarl.URL(url)
        str_url = str(yarl_url)

        def dl(url: str) -> int:
            r = self.__session.get(url, headers = self.headers)
            _log.debug(f'GET {url} returned code: {r.status_code}')

            data = r.content
            if isinstance(fp, io.BufferedIOBase):
                return (fp.write(data))
            else:
                with open(fp, 'wb') as f:
                    return f.write(data)

        # If it's a direct URL
        if all([x in str(yarl_url.host) for x in ['thumbs', 'redgifs']]):
            match = re.match(REDGIFS_THUMBS_RE, str_url)
            if match:
                return (dl(str_url))
            raise TypeError(f'"{str_url}" is an invalid RedGifs URL.')

        # If it's a 'watch' URL
        if 'watch' in yarl_url.path:
            id = yarl_url.path.strip('/watch/')
            hd_url = self.get_gif(id)['gif']['urls']['hd']
            return (dl(hd_url))

        # Shouldn't reach here
        return 1


class AsyncHttp(HTTP):
    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        *,
        proxy: Optional[str] = None,
        proxy_auth: Optional[ProxyAuth] = None
    ) -> None:

        if session is not None and not isinstance(session, aiohttp.ClientSession):
            raise RuntimeError("session is not of type aiohttp.ClientSession")

        self.__session: aiohttp.ClientSession = session or aiohttp.ClientSession()
        self.headers: Dict[str, str] = {
            'User-Agent': f'redgifs (https://github.com/scrazzz/redgifs {__version__}) Python/{sys.version[:3]}'
        }
        self.proxy: Optional[yarl.URL] = yarl.URL(proxy) if proxy else None
        self.proxy_auth: Optional[ProxyAuth] = proxy_auth

        # Set proxy auth
        if self.proxy_auth and self.proxy:
            self._proxy_auth = aiohttp.BasicAuth(self.proxy_auth.username, self.proxy_auth.password)
        else:
            self._proxy_auth = None

    async def request(self, route: Route, **kwargs: Any) -> Any:
        url: str = route.url
        method: str = route.method
        async with self.__session.request(
            method, url, headers=self.headers, proxy=str(self.proxy) if self.proxy else None, proxy_auth=self._proxy_auth, **kwargs
        ) as resp:
            _log.debug(f'{method} {url} returned code: {resp.status}')
            js = await resp.json()
            if resp.status == 200:
                _log.debug(f'{method} {url} received: {js}')
                return js
            else:
                raise HTTPException(resp, js)

    async def download(self, url: str, fp: Union[str, bytes, os.PathLike[Any], io.BufferedIOBase]) -> int:
        yarl_url = yarl.URL(url)
        str_url = str(yarl_url)

        async def dl(url: str) -> int:
            async with self.__session.get(url, headers = self.headers) as r:
                _log.debug(f'GET {str_url} returned code: {r.status}')
                
                data = await r.read()
                if isinstance(fp, io.BufferedIOBase):
                    return (fp.write(data))
                else:
                    with open(fp, 'wb') as f:
                        return f.write(data)

        # If it's a direct URL
        if all([x in str(yarl_url.host) for x in ['thumbs', 'redgifs']]):
            match = re.match(REDGIFS_THUMBS_RE, str_url)
            if match:
                return (await dl(str_url))
            raise TypeError(f'"{str_url}" is an invalid RedGifs URL.')

        # If it's a 'watch' URL
        if 'watch' in yarl_url.path:
            id = yarl_url.path.strip('/watch/')
            hd_url = self.get_gif(id)['gif']['urls']['hd']
            return (await dl(hd_url))

        # Shouldn't reach here
        return 1

    async def close(self) -> None:
        await self.__session.close()
