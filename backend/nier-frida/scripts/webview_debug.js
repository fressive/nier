'use strict';

const NIER_FORCE_SYSTEM_BACK = __NIER_FORCE_SYSTEM_BACK__;
const NIER_TARGET_PACKAGE = __NIER_TARGET_PACKAGE__;

function emit(type, details) {
  const payload = details || {};
  payload.type = type;
  send(payload);
}

function installForceSystemBack() {
  const installed = [];
  let activityOnBackPressed = null;

  let platformRegistrationHooked = false;
  let androidXRegistrationHooked = false;
  let androidXDispatchHooked = false;
  let resolvingApplicationClass = false;
  const hookedApplicationClasses = {};

  function isTargetClass(className) {
    return NIER_TARGET_PACKAGE &&
      (className === NIER_TARGET_PACKAGE ||
       className.startsWith(NIER_TARGET_PACKAGE + '.'));
  }

  function hookPlatformRegistration() {
    if (platformRegistrationHooked) {
      return;
    }
    try {
      const dispatcher = Java.use('android.window.OnBackInvokedDispatcher');
      const register = dispatcher.registerOnBackInvokedCallback.overload(
        'int',
        'android.window.OnBackInvokedCallback'
      );
      register.implementation = function (priority, callback) {
        emit('back_callback_blocked', {
          framework: 'android.window.OnBackInvokedDispatcher',
          priority: priority,
        });
        return;
      };
      platformRegistrationHooked = true;
      installed.push('platform-registration');
    } catch (error) {
      emit('back_hook_warning', {
        framework: 'android.window.OnBackInvokedDispatcher',
        error: String(error),
      });
    }
  }

  function hookAndroidXRegistration() {
    if (androidXRegistrationHooked) {
      return;
    }
    try {
      const dispatcher = Java.use('androidx.activity.OnBackPressedDispatcher');
      dispatcher.addCallback.overloads.forEach(function (overload) {
        overload.implementation = function () {
          emit('back_callback_blocked', {
            framework: 'androidx.activity.OnBackPressedDispatcher',
          });
          return;
        };
      });
      androidXRegistrationHooked = true;
      installed.push('androidx-registration');
    } catch (error) {
      emit('back_hook_warning', {
        framework: 'androidx.activity.OnBackPressedDispatcher',
        error: String(error),
      });
    }
  }

  function hookAndroidXDispatch() {
    if (androidXDispatchHooked) {
      return;
    }
    try {
      const dispatcher = Java.use('androidx.activity.OnBackPressedDispatcher');
      const onBackPressed = dispatcher.onBackPressed.overload();
      onBackPressed.implementation = function () {
        const fallbackFields = ['mFallbackOnBackPressed', 'fallbackOnBackPressed'];
        for (let index = 0; index < fallbackFields.length; index += 1) {
          try {
            const fallback = this[fallbackFields[index]].value;
            if (fallback) {
              fallback.run();
              emit('back_default_invoked', {
                framework: 'androidx.activity.OnBackPressedDispatcher',
              });
              return;
            }
          } catch (ignored) {
            // AndroidX field names vary between releases.
          }
        }
        // Keep the original behavior if this AndroidX revision does not
        // expose its fallback runnable to Frida.
        return onBackPressed.call(this);
      };
      androidXDispatchHooked = true;
      installed.push('androidx-dispatch');
    } catch (error) {
      emit('back_hook_warning', {
        framework: 'androidx.activity.OnBackPressedDispatcher.onBackPressed',
        error: String(error),
      });
    }
  }

  function hookApplicationClass(className) {
    if (!isTargetClass(className) || hookedApplicationClasses[className]) {
      return 0;
    }
    hookedApplicationClasses[className] = true;
    let hooks = 0;
    try {
      const clazz = Java.use(className);
      if (clazz.onBackPressed) {
        clazz.onBackPressed.overloads.forEach(function (overload) {
          if (overload.argumentTypes.length !== 0) {
            return;
          }
          overload.implementation = function () {
            emit('back_callback_blocked', {
              framework: className + '.onBackPressed',
            });
            return activityOnBackPressed.call(this);
          };
          hooks += 1;
        });
      }
      if (clazz.dispatchKeyEvent) {
        clazz.dispatchKeyEvent.overloads.forEach(function (overload) {
          const argumentTypes = overload.argumentTypes;
          if (argumentTypes.length !== 1 ||
              String(argumentTypes[0].className) !== 'android.view.KeyEvent') {
            return;
          }
          overload.implementation = function (event) {
            let isBack = false;
            try {
              isBack = event !== null && event.getKeyCode() === 4;
            } catch (ignored) {
              isBack = false;
            }
            if (!isBack) {
              return overload.call(this, event);
            }
            emit('back_callback_blocked', {
              framework: className + '.dispatchKeyEvent',
            });
            activityOnBackPressed.call(this);
            return true;
          };
          hooks += 1;
        });
      }
    } catch (ignored) {
      // A class can disappear while the application is loading.
    }
    return hooks;
  }

  function handleLoadedClass(className) {
    if (className === 'android.window.OnBackInvokedDispatcher') {
      hookPlatformRegistration();
    } else if (className === 'androidx.activity.OnBackPressedDispatcher') {
      hookAndroidXRegistration();
      hookAndroidXDispatch();
    }
    if (isTargetClass(className) && activityOnBackPressed !== null &&
        !resolvingApplicationClass) {
      resolvingApplicationClass = true;
      try {
        const hooks = hookApplicationClass(className);
        if (hooks > 0 && installed.indexOf('application-legacy') === -1) {
          installed.push('application-legacy');
        }
      } finally {
        resolvingApplicationClass = false;
      }
    }
  }

  try {
    const Activity = Java.use('android.app.Activity');
    activityOnBackPressed = Activity.onBackPressed.overload();
  } catch (error) {
    emit('back_hook_warning', {
      framework: 'android.app.Activity',
      error: String(error),
    });
  }

  hookPlatformRegistration();
  hookAndroidXRegistration();
  hookAndroidXDispatch();

  if (NIER_TARGET_PACKAGE && activityOnBackPressed !== null) {
    try {
      Java.enumerateLoadedClassesSync().forEach(function (className) {
        handleLoadedClass(className);
      });
    } catch (error) {
      emit('back_hook_warning', {
        framework: 'application legacy back callbacks',
        error: String(error),
      });
    }

    try {
      const ClassLoader = Java.use('java.lang.ClassLoader');
      let loaderHooks = 0;
      try {
        const loadClass = ClassLoader.loadClass.overload('java.lang.String');
        loadClass.implementation = function (className) {
          const result = loadClass.call(this, className);
          handleLoadedClass(String(className));
          return result;
        };
        loaderHooks += 1;
      } catch (ignored) {
        // Some runtimes expose only the overload with the resolve flag.
      }
      try {
        const loadClassWithResolve = ClassLoader.loadClass.overload(
          'java.lang.String',
          'boolean'
        );
        loadClassWithResolve.implementation = function (className, resolve) {
          const result = loadClassWithResolve.call(this, className, resolve);
          handleLoadedClass(String(className));
          return result;
        };
        loaderHooks += 1;
      } catch (ignored) {
        // The one-argument overload is sufficient on older runtimes.
      }
      if (loaderHooks > 0) {
        installed.push('application-class-loading');
      }
    } catch (error) {
      emit('back_hook_warning', {
        framework: 'java.lang.ClassLoader.loadClass',
        error: String(error),
      });
    }
  }

  emit('back_hook_installed', {frameworks: installed});
  return installed;
}

Java.perform(function () {
  try {
    if (!Java.available) {
      throw new Error('the target process has no Java VM');
    }

    try {
      const WebView = Java.use('android.webkit.WebView');
      const setter = WebView.setWebContentsDebuggingEnabled.overload('boolean');

      setter.implementation = function (enabled) {
        emit('webview_debugging_requested', {
          requested: !!enabled,
          enabled: true,
        });
        return setter.call(this, true);
      };

      // In spawn mode this runs before the app is resumed and before its first
      // WebView is constructed. In attach mode it enables debugging for future
      // WebViews and observes later setter calls.
      // Android requires this static setter to run on the application's main
      // thread. The replacement above still covers later app-side calls;
      // schedule the initial enablement separately for attach mode.
      Java.scheduleOnMainThread(function () {
        try {
          setter.call(WebView, true);
        } catch (error) {
          emit('webview_hook_warning', {error: String(error)});
        }
      });
    } catch (error) {
      // Back enforcement is useful for non-WebView apps as well. A missing or
      // incompatible WebView class must not prevent that requested behavior.
      emit('webview_hook_warning', {error: String(error)});
    }

    const backHooks = NIER_FORCE_SYSTEM_BACK ? installForceSystemBack() : [];
    send({
      type: 'ready',
      mode: 'root',
      force_system_back: NIER_FORCE_SYSTEM_BACK,
      back_hooks: backHooks,
    });
  } catch (error) {
    send({type: 'error', error: String(error)});
  }
});
