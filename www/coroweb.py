#!/usr/bin/env python3
# -*- coding: utf-8 -*-

'''
Web Frame.
'''

__author__ = 'ZcJ'

import asyncio, os, inspect, logging, functools
from urllib import parse
from aiohttp import web
from apis import APIError

# 建立视图函数装饰器，用来存储、附带URL信息

def get(path):
    '''
    Define decorator @get('/path')
    '''
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper.__method__ = 'GET'
        wrapper.__route__ = path
        return wrapper
    return decorator

def post(path):
    '''
    Define decorator @post('/path')
    '''
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper.__method__ = 'POST'
        wrapper.__route__ = path
        return wrapper
    return decorator


# 使用inspect模块，检查视图函数的参数
 
# inspect.Parameter.kind 类型：
# POSITIONAL_ONLY          位置参数
# KEYWORD_ONLY             命名关键字参数
# VAR_POSITIONAL           可选参数 *args
# VAR_KEYWORD              关键字参数 **kw
# POSITIONAL_OR_KEYWORD    位置或必选参数

# 获取无默认值的命名关键字参数
def get_required_kw_args(fn):
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        # 如果视图函数存在命名关键字参数，且默认值为空，获取它的key（参数名）
        if param.kind == inspect.Parameter.KEYWORD_ONLY and param.default == inspect.Parameter.empty:
            args.append(name)
    return tuple(args)

# 获取命名关键字参数
def get_named_kw_args(fn):
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            args.append(name)
    return tuple(args)

# 判断是否有命名关键字参数
def has_named_kw_args(fn):
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            return True

# 判断是否有关键字参数
def has_var_kw_arg(fn):
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True

# 判断是否含有名叫'request'的参数，且位置在最后
def has_request_arg(fn):
    sig = inspect.signature(fn)
    params = sig.parameters
    found = False
    for name, param in params.items():
        if name == 'request':
            found = True
            continue
        if found and (param.kind != inspect.Parameter.VAR_POSITIONAL and param.kind != inspect.Parameter.KEYWORD_ONLY and param.kind != inspect.Parameter.VAR_KEYWORD):
            # 若判断为True，表明param只能是位置参数。且该参数位于request之后，故不满足条件，报错
            raise ValueError('request parameter must be the last named parameter in function: %s%s' % (fn.__name__, str(sig)))
    return found

# 定义RequestHandler从视图函数中分析其需要接受的参数，从web.Request中获取必要的参数
# 调用视图函数，然后把结果转换为web.Response对象，符合aiohttp框架要求
class RequestHandler(object):

    def __init__(self, app, fn):
        self._app = app
        self._func = fn
        self._has_request_arg = has_request_arg(fn)
        self._has_var_kw_arg = has_var_kw_arg(fn)
        self._has_named_kw_args = has_named_kw_args(fn)
        self._named_kw_args = get_named_kw_args(fn)
        self._required_kw_args = get_required_kw_args(fn)

    async def __call__(self, request):
        # 定义kw，用于保存request中参数
        kw = None
        # 若视图函数有命名关键词或关键词参数
        if self._has_var_kw_arg or self._has_named_kw_args:
            if request.method == 'POST':
                # 根据request参数中的content_type使用不同解析方法：
                # 如果content_type不存在，返回400错误
                if not request.content_type:
                    return web.HTTPBadRequest(text='Missing Content-Type.')
                ct = request.content_type.lower()
                # 如果是json格式数据
                if ct.startswith('application/json'):
                    # 仅解析body字段的json数据
                    params = await request.json()
                    # 如果request.json()没有返回dict对象
                    if not isinstance(params, dict):
                        return web.HTTPBadRequest(text='JSON body must be object.')
                    kw = params
                # 如果是form表单请求的编码形式
                elif ct.startswith('application/x-www-form-urlencoded') or ct.startswith('multipart/form-data'):
                    # 返回post的内容中解析后的数据，dict-like对象
                    params = await request.post()
                    # 组成dict，统一kw格式
                    kw = dict(**params)
                # 不支持其他数据格式
                else:
                    return web.HTTPBadRequest(text='Unsupported Content-Type: %s' % request.content_type)
            if request.method == 'GET':
                # 返回URL查询语句?后的键值，string形式
                qs = request.query_string
                if qs:
                    kw = dict()
                    '''
					解析url中?后面的键值对的内容
					qs = 'first=f,s&second=s'
					parse.parse_qs(qs, True).items()
					>>> dict([('first', ['f,s']), ('second', ['s'])])
                    '''
                    # 返回查询变量和值的映射，dict对象,True表示不忽略空格
                    for k, v in parse.parse_qs(qs, True).items():
                        kw[k] = v[0]
        # 若request中无参数
        if kw is None:
            # request.match_info返回dict对象。可变路由中的可变字段{variable}为参数名，传入request请求的path为值
			# 若存在可变路由：/a/{name}/c，可匹配path为：/a/jack/c的request
			# 则request.match_info返回{name = jack}
            kw = dict(**request.match_info)
        # 若request中有参数
        else:
            # 若视图函数只有命名关键字参数没有关键字参数
            if (not self._has_var_kw_arg) and self._has_named_kw_args:
                # remove all unamed kw:
                copy = dict()
                for name in self._named_kw_args:
                    if name in kw:
                        copy[name] = kw[name]
                # kw中只存在命名关键字参数
                kw = copy
            # 将request.match_info中的参数传入kw
            for k, v in request.match_info.items():
                # 检查kw中的参数是否和match_info中的重复
                if k in kw:
                    logging.warning('Duplicate arg name in named arg and kw args: %s' % k)
                kw[k] = v
        # 若视图函数存在request参数
        if self._has_request_arg:
            kw['request'] = request
        # 若视图函数存在无默认值的命名关键词参数
        if self._required_kw_args:
            for name in self._required_kw_args:
                # 若未传入必须参数值，报错
                if not name in kw:
                    return web.HTTPBadRequest(text='Missing argument: %s' % name)
        # 至此，kw为视图函数fn真正能调用的参数
		# request请求中的参数，终于传递给了视图函数
        logging.info('call with args: %s' % str(kw))
        try:
            r = await self._func(**kw)
            return r
        except APIError as e:
            return dict(error=e.error, data=e.data, message=e.message)

# 添加静态文件，如image，css，javascript等    
def add_static(app):
    # 拼接static文件目录
    # __file__表示当前.py文件的路径
    # os.path.dirname(__file__)表示当前.py文件所在文件夹的路径
    # os.path.abspath()表示当前.py文件的绝对路径
    # 一般组合着来用，在拼接路径的时候注意后面的路径前面不需要加\，会自动补上
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    app.router.add_static('/static/', path)
    logging.info('add static %s => %s' % ('/static/', path))

# 编写一个add_route函数，用来注册一个视图函数(URL处理函数)    
def add_route(app, fn):
    method = getattr(fn, '__method__', None)
    path = getattr(fn, '__route__', None)
    if path is None or method is None:
        raise ValueError('@get or @post not defined in %s.' % str(fn))
    # 判断URL处理函数是否协程和生成器
    if not asyncio.iscoroutinefunction(fn) and not inspect.isgeneratorfunction(fn):
        # 将fn转变成协程
        fn = asyncio.coroutine(fn)
    logging.info('add route %s %s => %s(%s)' % (method, path, fn.__name__, ', '.join(inspect.signature(fn).parameters.keys())))
    # 在app中注册经RequestHandler类封装的视图函数
    app.router.add_route(method, path, RequestHandler(app, fn))

# 导入模块，批量注册视图函数
def add_routes(app, module_name):
    # 从右侧检索，返回索引；若无，返回-1
    n = module_name.rfind('.')
    # 导入整个模块
    if n == (-1):
        # __import__ 作用同import语句，但__import__是一个函数，并且只接收字符串作为参数
		# __import__('os', globals(), locals(), ['path', 'pip'], 0) ,等价于from os import path, pip
        mod = __import__(module_name, globals(), locals())
    else:
        name = module_name[n+1:]
        # 只获取最终导入的模块，为后续调用dir()
        mod = getattr(__import__(module_name[:n], globals(), locals(), [name]), name)
    # dir()迭代出mod模块中所有的类、实例及函数等对象，str形式
    for attr in dir(mod):
        # 忽略'_'开头的对象，直接继续for循环
        if attr.startswith('_'):
            continue
        fn = getattr(mod, attr)
        # 确保是函数
        if callable(fn):
            # 确保视图函数存在method和path
            method = getattr(fn, '__method__', None)
            path = getattr(fn, '__route__', None)
            if method and path:
                add_route(app, fn)