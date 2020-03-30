import orm
import asyncio
from models import User, Blog, Comment

loop = asyncio.get_event_loop()
async def test():
    await orm.create_pool(user='www-data', password='www-data', db='awesome', loop=loop)

    # u1 = User(name='ZcJ', email='test1@example.com', passwd='1234567890', image='about:blank')
    # u2 = User(name='Love', email='test2@example.com', passwd='1234567890', image='about:blank')
    # u3 = User(name='Rqq', email='test3@example.com', passwd='1234567890', image='about:blank')

    # await u1.save()
    # await u2.save()
    # await u3.save()

loop.run_until_complete(test())