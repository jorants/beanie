from typing import (
    Union,
    Optional,
    List,
    Tuple,
    Type,
    Mapping,
    TYPE_CHECKING,
    TypeVar,
    Dict,
    Any,
    cast,
)

from pydantic import BaseModel
from pymongo.client_session import ClientSession
from pymongo.results import UpdateResult

from beanie.exceptions import DocumentNotFound
from beanie.odm.enums import SortDirection
from beanie.odm.interfaces.aggregate import AggregateMethods
from beanie.odm.interfaces.session import SessionMethods
from beanie.odm.interfaces.update import (
    UpdateMethods,
)
from beanie.odm.operators.find import BaseFindOperator
from beanie.odm.operators.find.logical import And
from beanie.odm.queries.aggregation import AggregationQuery
from beanie.odm.queries.cursor import BaseCursorQuery
from beanie.odm.queries.delete import (
    DeleteQuery,
    DeleteMany,
    DeleteOne,
)
from beanie.odm.queries.update import (
    UpdateQuery,
    UpdateMany,
    UpdateOne,
)
from beanie.odm.utils.projection import get_projection
from pymongo.client_session import ClientSession
from pymongo.results import UpdateResult

from pydantic import BaseModel, conint, validator

from motor.motor_asyncio import AsyncIOMotorCursor

if TYPE_CHECKING:
    from beanie.odm.documents import DocType


    
class FindQuery(SessionMethods, UpdateMethods, BaseCursorQuery):
    """
    A FindQuery  is the result of running find() on a beanie Document. It stores limits and so on.
    """
    document_model: Type["DocType"]
    find_expressions: List[Union[BaseFindOperator,Mapping[str, Any]]] = []
    projection_model: Type[BaseModel] = None
    sort_expressions: List[Tuple[str, SortDirection]] = []
    skip_number : conint(ge = 0) = 0
    limit_number : conint(ge = 0) = 0
    is_single : bool = False

    cursor : Optional[AsyncIOMotorCursor] = None
    
    @validator('projection_model', pre = True, always = True)
    def default_projection_model(cls,val, values):
        return val if val is not None else values['document_model']

    @validator('sort_expressions', each_item = True, pre = True)
    def validate_sort_items(cls, val):
        if val is None:
            return None # Filtered by next validator
        elif isinstance(val, tuple):
            return val
        elif isinstance(val, str):
            if val.startswith("+"):
                return (val[1:], SortDirection.ASCENDING)
            elif val.startswith("-"):
                return (val[1:], SortDirection.DESCENDING)
            else:
                return (val, SortDirection.ASCENDING)
        else:
            raise TypeError("Wrong sort type")

    @validator('sort_expressions',pre=True)
    def validate_sort_no_none(cls,val):
        return [item for item in val if item is not None]


    class Config:
        validate_assignment = True
    
    # ------------- Setters ---------------
    def _copy_update(self,**kwargs):
        res = self.copy()
        for key,value in kwargs.items():
            # set all in a way that trigger validation
            setattr(res,key,value)
        return res

    def limit(self, limit_number : int) -> 'FindQuery':
        """
        Sets the limit for a find query.
        :param limit_number: Positive int denoting the limit or 0 to denote no limit
        :return: New Find Query
        """
        return self._copy_update(limit_number = limit_number)

    def skip(self, skip_number : int) -> 'FindQuery':
        """
        Sets the skip size for a find query.
        :param skip_number: Positive int denoting the skip or 0 to denote no skip
        :return: New Find Query
        """
        return self._copy_update(skip_number = skip_number)
        
    def project(
            self,
            projection_model: Optional[Type[BaseModel]],
    ) -> 'FindQuery':
        """
        Sets projection parameter

        :param projection_model: Optional[Type[BaseModel]] - projection model
        :return: New Find Query
        """
        return self._copy_update(projection_model = projection_model)

    def one(self, is_single : bool = True):
        return self._copy_update(is_single = is_single, limit_number = 1)

    def sort(
        self,
        *args: Union[
                str, Tuple[str, SortDirection], List[Tuple[str, SortDirection]]
            ]
    ) -> 'FindQuery':
        """
        Add sort parameters.
        Can add multiple parameters by giving multiple arguments, will sort in order of parameters.
        Optionally the different sort parameters may be passed as a list in the first argument instead.
        :return: FindQuery
        """
        if len(args) == 0:
            raise ValueError("'sort()' requires arguments.")
        elif len(args) == 1 and isinstance(args[0],list):
            return self.sort(*args[0])
        else:
            # Add new options add start, so we still sort by the preexisting ones after.
            res = self._copy_update(sort_expressions = list(args) + self.sort_expressions)
            return res
            
    
    def find(
        self,
            *args: Mapping[str, Any],
            skip: Optional[int] = None,
            limit: Optional[int] = None,
            sort: Union[None, str, List[Tuple[str, SortDirection]]] = None,
            one : Optional[bool] = None,
            projection_model: Optional[Type[BaseModel]] = None,
            session: Optional[ClientSession] = None
    ) -> 'FindQuery':
        """
        Find documents by criteria

        :param args: *Mapping[str, Any] - search criteria
        :param skip: Optional[int] - The number of documents to omit.
        :param limit: Optional[int] - The maximum number of results to return.
        :param sort: Union[None, str, List[Tuple[str, SortDirection]]] - A key
        or a list of (key, direction) pairs specifying the sort order
        for this query.
        :param projection_model: Optional[Type[BaseModel]] - projection model
        :param session: Optional[ClientSession] - pymongo session
        :return: FindMany - query instance
        """
        res = self._copy_update(find_expressions = self.find_expressions + list(args))
        
        res = res.skip(skip) if skip is not None else res
        res = res.limit(limit) if limit is not None else res
        res = res.sort(sort) if sort is not None else res
        res = res.one(one) if one is not None else res
        res = res.project(projection_model) if projection_model is not None else res
        res = res.set_session(session) if session is not None else res
        return res


    find_many = find


    
    
    # ----------------- Getters --------------------
    def get_projection_model(self) -> Type[BaseModel]:
        return self.projection_model

        
    def get_filter_query(self) -> Mapping[str, Any]:
        if self.find_expressions:
            return And(*self.find_expressions)
        else:
            return {}

    # ---------------- Queries ----------------------
    def _find_query_params(self):
        params =  {"filter" : self.get_filter_query(),
                "projection" : get_projection(self.projection_model),
                "session" : self.session,
                "limit" : self.limit_number if not self.is_single else 1,
                "skip" : self.skip_number,
                "sort" : self.sort_expressions,
                }
        return params

    
    def __await__(self):
        """
        Run the query
        :return: Document (or projection) if `one` was called, otherwise a list of those.
        """
        params = self._find_query_params()
        if self.is_single:
            document: Dict[str, Any] = (
                yield from self.document_model.get_motor_collection().find_one(**params)
            )
            if document is None:
                return None
            return self.projection_model.parse_obj(document)
        else:
            return self.to_list().__await__()


    @property
    def motor_cursor(self):
        return self.document_model.get_motor_collection().find(
            **self._find_query_params()
        )

        
    async def count(self) -> int:
        """
        Number of found documents
        :return: int
        """
        # TODO handle one ?
        return (
            await self.document_model.get_motor_collection().count_documents(
                self.get_filter_query()
            )
        )




    # def upsert(
    #     self,
    #     *args: Mapping[str, Any],
    #     on_insert: "DocType",
    #     session: Optional[ClientSession] = None
    # ):
    #     """
    #     Create Update with modifications query
    #     and provide search criteria there

    #     :param args: *Mapping[str,Any] - the modifications to apply.
    #     :param on_insert: DocType - document to insert if there is no matched
    #     document in the collection
    #     :param session: Optional[ClientSession]
    #     :return: UpdateMany query
    #     """
    #     self.set_session(session)
    #     return (
    #         self.UpdateQueryType(
    #             document_model=self.document_model,
    #             find_query=self.get_filter_query(),
    #         )
    #         .upsert(*args, on_insert=on_insert)
    #         .set_session(session=self.session)
    #     )

    

        
      # def update(
    #     self, *args: Mapping[str, Any], session: Optional[ClientSession] = None
    # ):
    #     """
    #     Create Update with modifications query
    #     and provide search criteria there

    #     :param args: *Mapping[str,Any] - the modifications to apply.
    #     :param session: Optional[ClientSession]
    #     :return: UpdateMany query
    #     """
    #     self.set_session(session=session)
    #     return (
    #         self.UpdateQueryType(
    #             document_model=self.document_model,
    #             find_query=self.get_filter_query(),
    #         )
    #         .update(*args)
    #         .set_session(session=self.session)
    #     )

    # def delete(
    #     self, session: Optional[ClientSession] = None
    # ) -> Union[DeleteOne, DeleteMany]:
    #     """
    #     Provide search criteria to the Delete query

    #     :param session: Optional[ClientSession]
    #     :return: Union[DeleteOne, DeleteMany]
    #     """
    #     self.set_session(session=session)
    #     return self.DeleteQueryType(
    #         document_model=self.document_model,
    #         find_query=self.get_filter_query(),
    #     ).set_session(session=session)
   

    # def aggregate(
    #     self,
    #     aggregation_pipeline: List[Any],
    #     projection_model: Optional[Type[BaseModel]] = None,
    #     session: Optional[ClientSession] = None,
    # ) -> AggregationQuery:
    #     """
    #     Provide search criteria to the [AggregationQuery](https://roman-right.github.io/beanie/api/queries/#aggregationquery)

    #     :param aggregation_pipeline: list - aggregation pipeline. MongoDB doc:
    #     <https://docs.mongodb.com/manual/core/aggregation-pipeline/>
    #     :param projection_model: Type[BaseModel] - Projection Model
    #     :param session: Optional[ClientSession] - PyMongo session
    #     :return:[AggregationQuery](https://roman-right.github.io/beanie/api/queries/#aggregationquery)
    #     """
    #     self.set_session(session=session)
    #     return AggregationQuery(
    #         aggregation_pipeline=aggregation_pipeline,
    #         document_model=self.document_model,
    #         projection_model=projection_model,
    #         find_query=self.get_filter_query(),
    #     ).set_session(session=self.session)



    def find_one(self,*args, **kwargs) -> 'FindQuery':
        """
        Find one document by criteria. Same as `.find(...).one()`
        """
        return self.find(*args,**kwargs).one()

    # def update_one(
    #     self, *args: Mapping[str, Any], session: Optional[ClientSession] = None
    # ) -> UpdateOne:
    #     """
    #     Create [UpdateOne](https://roman-right.github.io/beanie/api/queries/#updateone) query using modifications and
    #     provide search criteria there
    #     :param args: *Mapping[str,Any] - the modifications to apply
    #     :param session: Optional[ClientSession] - PyMongo sessions
    #     :return: [UpdateOne](https://roman-right.github.io/beanie/api/queries/#updateone) query
    #     """
    #     return self.update(*args, session=session)

    # def delete_one(self, session: Optional[ClientSession] = None) -> DeleteOne:
    #     """
    #     Provide search criteria to the [DeleteOne](https://roman-right.github.io/beanie/api/queries/#deleteone) query
    #     :param session: Optional[ClientSession] - PyMongo sessions
    #     :return: [DeleteOne](https://roman-right.github.io/beanie/api/queries/#deleteone) query
    #     """
    #     # We need to cast here to tell mypy that we are sure about the type.
    #     # This is because delete may also return a DeleteOne type in general, and mypy can not be sure in this case
    #     # See https://mypy.readthedocs.io/en/stable/common_issues.html#narrowing-and-inner-functions
    #     return cast(DeleteOne, self.delete(session=session))

    # async def replace_one(
    #     self,
    #     document: "DocType",
    #     session: Optional[ClientSession] = None,
    # ) -> UpdateResult:
    #     """
    #     Replace found document by provided
    #     :param document: Document - document, which will replace the found one
    #     :param session: Optional[ClientSession] - PyMongo session
    #     :return: UpdateResult
    #     """
    #     self.set_session(session=session)
    #     result: UpdateResult = (
    #         await self.document_model.get_motor_collection().replace_one(
    #             self.get_filter_query(),
    #             document.dict(by_alias=True, exclude={"id"}),
    #             session=self.session,
    #         )
    #     )

    #     if not result.raw_result["updatedExisting"]:
    #         raise DocumentNotFound
    #     return result
