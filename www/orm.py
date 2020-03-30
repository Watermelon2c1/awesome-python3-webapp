#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ZcJ'

import asyncio, logging
import aiomysql

# 打印SQL语句，使用args防止SQL注入
def log(sql, args=()):
    logging.info('SQL: %s' % sql)

# 创建连接池
async def create_pool(loop, **kw):
    logging.info('create database connection pool...')
    global __pool  # 定义全局变量__pool存储连接池
    __pool = await aiomysql.create_pool(
        host=kw.get('host', 'localhost'),
        port=kw.get('port', 3306),
        user=kw['user'],
        password=kw['password'],
        db=kw['db'],
        charset=kw.get('charset', 'utf8'),  # 默认编码为UTF-8
        autocommit=kw.get('autocommit', True),  # 默认自动提交
        maxsize=kw.get('maxsize', 10),
        minsize=kw.get('minsize', 1),
        loop=loop
    )

# 定义select函数
async def select(sql, args, size=None):
    log(sql, args)
    global __pool
    async with __pool.get() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:  # 打开游标
            await cur.execute(sql.replace('?', '%s'), args or ())  # 将SQL语句的占位符？替换为MySQL的占位符%s
            if size:
                rs = await cur.fetchmany(size)  # 获取最多指定size数量的记录
            else:
                rs = await cur.fetchall()  # 获取所有记录
        logging.info('rows returned: %s' % len(rs))
        return rs  # 返回查询结果

# 定义通用的execute函数，可执行Insert、Update、Delete语句
async def execute(sql, args, autocommit=True):
    log(sql)
    async with __pool.get() as conn:
        if not autocommit:
            await conn.begin()  # 如果不是自动提交，则开始事务
        try:  # 无论是否自动提交，都执行try中代码
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql.replace('?', '%s'), args or ())
                affected = cur.rowcount
            if not autocommit:
                await conn.commit()  # 如果不是自动提交，则提交事务
        except BaseException:
            if not autocommit:
                await conn.rollback()  # 如果不是自动提交，则回退事务
            raise
        return affected  # 返回受影响的行数

# 创建问号序列，构造默认INSERT语句
def create_args_string(num):
    L = []
    for _ in range(num):
        L.append('?')
    return ', '.join(L)  # ?, ?, ?, ?, ?, ?, ?

# 定义Field类及其子类，负责保存数据库表的字段名、字段类型等数据
class Field(object):

    def __init__(self, name, column_type, primary_key, default):
        self.name = name  # 字段名
        self.column_type = column_type  # 列类型
        self.primary_key = primary_key  # 主键
        self.default = default  # 默认值
    
    def __str__(self):  # 定制print(Field('xx'))效果
        return '<%s, %s:%s>' % (self.__class__.__name__, self.column_type, self.name)

# 定义string类型
class StringField(Field):

    def __init__(self, name=None, primary_key=False, default=None, ddl='varchar(100)'):
        super().__init__(name, ddl, primary_key, default)

# 定义布尔类型
class BooleanField(Field):

    def __init__(self, name=None, default=False):
        super().__init__(name, 'boolean', False, default)

# 定义int类型
class IntegerField(Field):

    def __init__(self, name=None, primary_key=False, default=0):
        super().__init__(name, 'bigint', primary_key, default)

# 定义float类型
class FloatField(Field):

    def __init__(self, name=None, primary_key=False, default=0.0):
        super().__init__(name, 'real', primary_key, default)

# 定义text类型
class TextField(Field):

    def __init__(self, name=None, default=None):
        super().__init__(name, 'text', False, default)

# 定义metaclass元类
class ModelMetaclass(type):

    def __new__(cls, name, bases, attrs):
        # 排除Model类本身
        if name=='Model':
            return type.__new__(cls, name, bases, attrs)
        # 获取表名
        tableName = attrs.get('__table__', None) or name
        logging.info('found model: %s (table: %s)' % (name, tableName))
        # 获取所有的Field和主键名
        mappings = dict()
        fields = []
        primaryKey = None
        for k, v in attrs.items():
            if isinstance(v, Field):
                logging.info('  found mapping: %s ==> %s' % (k, v))
                mappings[k] = v
                # 找到主键
                if v.primary_key:
                    # 主键唯一不可重复
                    if primaryKey:
                        raise RuntimeError('Duplicate primary key for field: %s' % k)
                    primaryKey = k
                else:
                    fields.append(k)
        # 必须设置主键
        if not primaryKey:
            raise RuntimeError('Primary key not found.')
        # 从类属性中删除Field属性，否则容易造成运行时错误（实例的属性会遮盖类的同名属性）
        for k in mappings.keys():
            attrs.pop(k)
        escaped_fields = list(map(lambda f: '`%s`' % f, fields))
        attrs['__mappings__'] = mappings  # 保存属性和列的映射关系
        attrs['__table__'] = tableName  # 保存表名
        attrs['__primary_key__'] = primaryKey  # 保存主键属性名
        attrs['__fields__'] = fields # 保存除主键外的属性名
        # 构造默认的SELECT、INSERT、UPDATE和DELETE语句
        attrs['__select__'] = 'select `%s`, %s from `%s`' % (primaryKey, ', '.join(escaped_fields), tableName)
        attrs['__insert__'] = 'insert into `%s` (%s, `%s`) values (%s)' % (tableName, ', '.join(escaped_fields), primaryKey, create_args_string(len(escaped_fields) + 1))
        attrs['__update__'] = 'update `%s` set %s where `%s`=?' % (tableName, ', '.join(map(lambda f: '`%s`=?' % (mappings.get(f).name or f), fields)), primaryKey)
        attrs['__delete__'] = 'delete from `%s` where `%s`=?' % (tableName, primaryKey)
        return type.__new__(cls, name, bases, attrs)

# 定义所有ORM映射的基类Model
class Model(dict, metaclass=ModelMetaclass):

    def __init__(self, **kw):
        super(Model, self).__init__(**kw)
    
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(r"'Model' object has no attribute '%s'" % key)
    
    def __setattr__(self, key, value):
        self[key] = value
    
    def getValue(self, key):
        return getattr(self, key, None)
    
    def getValueOrDefault(self, key):
        value = getattr(self, key, None)
        if value is None:
            field = self.__mappings__[key]
            if field.default is not None:
                value = field.default() if callable(field.default) else field.default
                logging.debug('using default value for %s: %s' % (key, str(value)))
                setattr(self, key, value)
        return value
    
    # 根据WHERE条件查找
    @classmethod
    async def findAll(cls, where=None, args=None, **kw):
        ' find objects by where clause'
        sql = [cls.__select__]
        if where:
            sql.append('where')
            sql.append(where)
        if args is None:
            args = []
        orderBy = kw.get('orderBy', None)
        if orderBy:
            sql.append('order by')
            sql.append(orderBy)
        limit = kw.get('limit', None)
        if limit is not None:
            sql.append('limit')
            if isinstance(limit, int):
                sql.append('?')
                args.append(limit)
            elif isinstance(limit, tuple) and len(limit) == 2:
                sql.append('?, ?')
                args.extend(limit)
            else:
                raise ValueError('Invalid limit value: %s' % str(limit))
        rs = await select(' '.join(sql), args)
        return [cls(**r) for r in rs]
    
    # 根据WHERE条件查找，但返回的是整数，适用于select count(*)类型的SQL
    @classmethod
    async def findNumber(cls, selectField, where=None, args=None):
        ' find number by select and where'
        sql = ['select %s __num__ from `%s`' % (selectField, cls.__table__)]
        if where:
            sql.append('where')
            sql.append(where)
        rs = await select(' '.join(sql), args, 1)
        if len(rs) == 0:
            return None
        return rs[0]['__num__']
    
    # 根据主键查找
    @classmethod
    async def find(cls, pk):
        ' find object by primary key'
        rs = await select('%s where `%s`=?' % (cls.__select__, cls.__primary_key__), [pk], 1)
        if len(rs) == 0:
            return None
        return cls(**rs[0])
    
    # 保存属性(INSERT操作)
    async def save(self):
        args = list(map(self.getValueOrDefault, self.__fields__))
        args.append(self.getValueOrDefault(self.__primary_key__))
        rows = await execute(self.__insert__, args)
        if rows != 1:
            logging.warn('failed to insert record: affected rows: %s' % rows)
    
    # 更新属性(UPDATE操作)
    async def update(self):
        args = list(map(self.getValue, self.__fields__))
        args.append(self.getValue(self.__primary_key__))
        rows = await execute(self.__update__, args)
        if rows != 1:
            logging.warn('failed to update by primary key: affected rows: %s' % rows)
    
    # 移除属性(DELETE操作)
    async def remove(self):
        args = [self.getValue(self.__primary_key__)]
        rows = await execute(self.__delete__, args)
        if rows != 1:
            logging.warn('failed to remove by primary key: affected rows: %s' % rows)