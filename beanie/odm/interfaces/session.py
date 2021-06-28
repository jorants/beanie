from typing import Optional

from pymongo.client_session import ClientSession
from pydantic import BaseModel

class SessionMethods(BaseModel):
    """
    Session methods
    """
    session : Optional[ClientSession] = None
    
    def set_session(self, session: Optional[ClientSession] = None):
        """
        Set pymongo session
        :param session: Optional[ClientSession] - pymongo session
        :return:
        """
        return self.copy(update = {'session':session})

    class Config:
        arbitrary_types_allowed = True
