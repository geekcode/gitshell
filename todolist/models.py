from django.db import models

from django.db import models
from django.core.cache import cache
from gitshell.objectscache.models import BaseModel
from gitshell.objectscache.da import query, queryraw, execute, count, get, get_many, get_version, get_sqlkey
from gitshell.objectscache.da import get_raw, get_raw_many

class ToDoList(models.Model):
    create_time = models.DateTimeField(auto_now=False, auto_now_add=True, null=False)
    modify_time = models.DateTimeField(auto_now=True, auto_now_add=True, null=False)
    visibly = models.SmallIntegerField(default=0, null=False)
    user_id = models.IntegerField(null=False, default=0) 
    scene_id = models.IntegerField(null=False, default=0)
    content = models.CharField(max_length=1024, default='')
    is_done = models.SmallIntegerField(default=0, null=False)

    @classmethod
    def create(self, user_id, scene_id, content, is_done):
        todolist = ToDoList()
        todolist.user_id = user_id
        todolist.scene_id = scene_id
        todolist.content = content
        todolist.is_done = is_done
        return todolist

class Scene(models.Model):
    create_time = models.DateTimeField(auto_now=False, auto_now_add=True, null=False)
    modify_time = models.DateTimeField(auto_now=True, auto_now_add=True, null=False)
    visibly = models.SmallIntegerField(default=0, null=False)
    user_id = models.IntegerField(null=False, default=0) 
    name = models.CharField(max_length=32, default='')
    meta = models.CharField(max_length=2048, default='')

    @classmethod
    def create(self, user_id, id, name):
        scene = Scene()
        scene.user_id = user_id
        scene.id = id
        scene.name = name
        return scene

class ToDoListManager():
    
    @classmethod
    def list_doing_todo_by_userId_sceneId(self, user_id, scene_id, offset, row_count):
        doing = 0
        offset = 0
        row_count = 200
        todos = query(ToDoList, user_id, 'todolist_l_userId_sceneId', [user_id, scene_id, 0, offset, row_count])
        return todos
    
    @classmethod
    def list_done_todo_by_userId_sceneId(self, user_id, scene_id, offset, row_count):
        done = 1
        offset = 0
        row_count = 200
        todos = query(ToDoList, user_id, 'todolist_l_userId_sceneId', [user_id, scene_id, 1, offset, row_count])
        return todos
    
    @classmethod
    def add_todo(self, user_id, scene_id, todo_text):
        pass

    @classmethod
    def get_todo_by_id(self, user_id, todo_id):
        todos = query(ToDoList, user_id, 'todolist_s_userId_id', [user_id, todo_id])
        if len(todos) > 0:
            return todos[0]
        return None

    @classmethod
    def done_todo(self, user_id, todo_id):
        todo = self.get_todo_by_id(user_id, todo_id)
        if todo != None:
            todo.is_done = 1
            todo.save()

    @classmethod
    def doing_todo(self, user_id, todo_id):
        todo = self.get_todo_by_id(user_id, todo_id)
        if todo != None:
            todo.is_done = 0
            todo.save()

    @classmethod
    def remove_todo(self, user_id, todo_id):
        todo = self.get_todo_by_id(user_id, todo_id)
        if todo != None:
            todo.visibly = 1
            todo.save()

    @classmethod
    def list_scene_by_userId(self, user_id, offset, row_count):
        scenes = query(Scene, user_id, 'scene_l_userId', [user_id, offset, row_count])
        return scenes

    @classmethod
    def get_scene_by_id(self, user_id, scene_id):
        scenes = query(Scene, user_id, 'scene_l_userId_id', [user_id, scene_id])
        if len(scenes) > 0:
            return scenes[0]
        return None

    @classmethod
    def get_scene_by_name(self, user_id, name):
        scenes = query(Scene, user_id, 'scene_l_userId_name', [user_id, name])
        if len(scenes) > 0:
            return scenes[0]
        return None

    @classmethod
    def add_scene(self, user_id, name):
        scene = self.get_scene_by_name(user_id, name)
        if scene != None:
            return scene.id
        scene = Scene()
        scene.user_id = user_id
        scene.name = name
        scene.save()
        return scene.id

    @classmethod
    def remove_scene(self, user_id, scene_id):
        scene = self.get_scene_by_id(user_id, scene_id)
        if scene != None:
            scene.visibly = 1
            scene.save()


