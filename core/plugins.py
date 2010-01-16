from models import PluginConfig

class PluginManager(object):
    """
    Manages the lifecycle of plugins.  Plugins may be registered making the
    manager awar of the plugin.  The plugins may then be enabled or disabled.
    """
    def __init__(self):
        self.plugins = {}

    def register(self, class_):
        """
        Registers a plugin with this manager.  Plugins are stored by __name__
        so that they may be looked up later.  Registration just makes them
        available to use on this installation, they don't add any functionality
        or check dependencies until they are enabled with enable_plugin()
        
        @param class_ - plugin class to register
        """
        print '[Info] Registering: ', class_.__name__
        self.plugins[class_.__name__] = class_

    def registers(self, classes):
        """
        Registers a collection of plugins
        @param classes - iterable of plugin Classes
        """
        for class_ in classes:
            self.register(plugin)

    
class RootPluginManager(PluginManager):
    """
    Specialized plugin manager that handles configuration and enabling/disabling
    of all plugins, whether they be registered directly with this plugin or
    are a sub-plugin.
    """
    def __init__(self):
        super(RootPluginManager, self).__init__()
        self.enabled = {}
    
    def autodiscover(self):
        """
        Auto-discover INSTALLED_APPS plugins.py modules and fail silently when
        not present. This forces an import on them to register any tasks they
        may want.
        """
        import imp
        import inspect
        from django.conf import settings
        
        # the path someone imports is important.  import all the different
        # possibilities so we can check them all
        from maintain.core.plugins import Plugin as PluginA
        from core.plugins import Plugin as PluginB
        subclasses = (PluginA, PluginB)
        
        print '[info] RootPluginManager - Autodiscovering Plugins'

        for app in filter(lambda x: x!='core', settings.INSTALLED_APPS):
            print '[info] checking app: %s' % app
            # For each app, we need to look for an plugin.py inside that app's
            # package. We can't use os.path here -- recall that modules may be
            # imported different ways (think zip files) -- so we need to get
            # the app's __path__ and look for plugin.py on that path.

            # Step 1: find out the app's __path__ Import errors here will (and
            # should) bubble up, but a missing __path__ (which is legal, but
            # weird) fails silently -- apps that do weird things with __path__
            # might need to roll their own plugin registration.
            try:
                app_path = __import__(app, {},{}, [app.split('.')[-1]]).__path__
            except AttributeError:
                continue

            # Step 2: use imp.find_module to find the app's plugin.py. For some
            # reason imp.find_module raises ImportError if the app can't be found
            # but doesn't actually try to import the module. So skip this app if
            # its tasks.py doesn't exist
            try:
                imp.find_module('plugins', app_path)
            except ImportError:
                continue

            # Step 3: load all the plugins in the plugin file
            module = __import__("%s.plugins" % app, {}, {}, ['Plugin'])
            configs = []
            for key, plugin in module.__dict__.items():
                if type(plugin)==type and not plugin in subclasses:
                    if issubclass(plugin, subclasses):
                        configs.append(self.register(plugin))
                        
            # Step 4: enable any plugins that were marked as enabled
            for config in configs:
                if config.enabled:
                    self.enable(config.name)

    def disable(self, name):
        """
        Disables a plugin, and any plugins that depend on it.
        
        @param name - name of plugin
        """
        if name not in self.enabled:
            return
        plugin = self.enabled[name]
        for depended_plugin in get_depended(plugin):
            self.__disable(depended_plugin)
        self.__disable(plugin)

    def __disable(self, plugin):
        """
        Private function for disabling a plugin.  disable() handles
        iteration to disable plugins thats depend on this one.  This function
        handles the actual steps to disable a plugin
        
        @param plugin - plugin instance to disable
        """
        del self.enabled[plugin.name]
        config = PluginConfig.objects.get(name=plugin.name)
        config.enabled = False
        config.save()

    def enable(self, name):
        """
        Enables a plugin allowing it to register its objects and or plugins
        for existing objects.  This also enables all dependencies returned by
        get_depends(plugin).
        
        If the plugin or any depends fail to load then any enabled depends
        should be disabled.
        
        @param plugin - name of plugin to register
        @returns - Instance of plugin that was created/running, or None if it
        failed to load
        """
        try:
            class_ = self.plugins[name]
        except KeyError:
            UnknownPluginException(name)

        # already enabled
        if name in self.enabled:
            return self.enabled[name]

        # as long as get_depends() returns the list in order from eldest to
        # youngest, we can just iterate the list making sure each one is enabled
        # if they all succeed then the plugin can also be enabled.
        enabled = []
        try:
            for depend in get_depends(class_):
                if depend.__name__ in self.enabled:
                    continue
                depend_plugin = self.__enable(depend)
                enabled.append(depend.__name__)
                
            plugin = self.__enable(class_)
        except Exception, e:
            #exception occured, rollback any enabled plugins in reverse order
            if enabled:
                enabled.reverse()
                for plugin in enabled:
                    self.disable(plugin)
            return None
        return plugin

    def __enable(self, class_):
        """
        Private function for enabling plugins.  enable_plugin handles iteration
        of dependencies.  This function handles the actual steps for enabling
        an individual plugin
        
        @param class_ - plugin class to enable
        """
        config = PluginConfig.objects.get(name=class_.__name__)
        plugin = class_(self)
        self.enabled[class_.__name__] = plugin
        config.enabled = True
        config.save()
        return plugin

    def register(self, class_):
        """
        Overridden to setup configuration
        
        @param class_ - Plugin class to register
        """
        super(RootPluginManager, self).register(class_)
        try:
            config = PluginConfig.objects.get(name=class_.__name__)
        except PluginConfig.DoesNotExist:
            config = PluginConfig()
            config.name = class_.__name__
            config.save()
        return config


class Plugin(object):
    """
    A Plugin is something that provides new functionality to PROJECT_NAME.  A
    plugin may register various objects such as Models, Views, and Processes
    or register plugins to existing objects
    
    Dependencies are created by 
    """
    manager = None
    depends = None
    description = 'I am a plugin who has not been described'
    
    def __init__(self, manager):
        """
        Creates the plugin.  Does *NOT* initialize the plugin.  This should only
        set configuration.
        """
        self.manager = manager
        self.name = self.__class__.__name__


def get_depended(plugin):
    """
    Gets a list of enabled plugins that depend on this plugin.  This looks up
    the depends of all active plugins searching for this plugin.  It also does
    a recursive search of any depended that is found.
    
    This differs from get_depends() in that it works with instances of the
    plugin rather than the class.  We're only concerned about depended plugins
    when they are enabled.
    
    the list returns sorted in order that removes all depended classes before
    their dependencies
    
    @param plugin - an enabled Plugin
    @returns list of Plugins
    """
    def add(value, set):
        """Helper Function for set-like lists"""
        if value not in set:
            set.append(value)
            
    #initial checks
    if not plugin.manager:
        return None
    
    #build depended list
    class_ = plugin.__class__
    depended = []
    for name, enabled in plugin.manager.enabled.items():
        depends = get_depends(enabled.__class__)
        # if the class_ is found in the list of depends, then this is a depended
        # add all of the depends after class_, we don't want to disable anything
        # that class_ depends on.
        if class_ in depends:
            for depend in depends[depends.index(class_)+1:]:
                add(plugin.manager.enabled[depend.__name__], depended)
            add(enabled, depended)
    depended.reverse()
    return depended


def get_depends(class_, descendents=set()):
    """
    Gets a list of dependencies for this plugin class, including recursive
    dependencies.  Dependencies will be sorted in order in which they need to
    be loaded
    
    @param class_ - class to get depends for
    @param descendents - child classes that are requesting depends for a parent.
    Used to check for cyclic dependency errors.
    @returns list of dependencies if any, else empty list
    """
    def add(value, set):
        """Helper Function for set-like lists"""
        if value not in set:
            set.append(value)
            
    # initial type checking
    if not class_.depends:
        return []
    elif not isinstance(class_.depends, (tuple, list)):
        class_depends = set((class_.depends,))
    else:
        class_depends = set(class_.depends)
        
    # check for cycles.  As we recurse into dependencies (parents) we build a
    # list of the path we took.  If at any point a parent depends on something
    # already on the list, its a cycle.
    descendents_ = set([class_]).union(descendents)
    if descendents_ and not descendents_.isdisjoint(class_depends):
        raise CyclicDependencyException(class_.__name__)

    # recurse into dependencies of parents (grandparents) checking all of them
    # and adding any that are found.  ancestors are added before descendents
    # to ensure proper loading order
    _depends = []
    for parent in class_depends:
        grandparents = get_depends(parent, descendents_)
        if grandparents:
            for grandparent in grandparents:
                add(grandparent, _depends)
        add(parent, _depends)
        
    return _depends


class CyclicDependencyException(Exception):
    """
    Exception thrown when a cycle is detected within dependencies of a module
    """
    pass


class UnknownPluginException(Exception):
    """
    Exception thrown when attempting to access a plugin that has not been
    registered.
    """
    pass
