'use strict';

const MAX_EXTRA_COUNT = 100;
const MAX_ARRAY_ITEMS = 64;
const MAX_TEXT_LENGTH = 4096;

function clipped(value, limit) {
  const text = String(value);
  return text.length > limit ? text.slice(0, limit) + '…' : text;
}

function tagged(type, value, truncated) {
  const result = {type: type, value: value};
  if (truncated) {
    result.truncated = true;
  }
  return result;
}

function unsupported(value) {
  let className = 'unknown';
  try {
    className = String(value.getClass().getName());
  } catch (ignored) {
    // The caller still gets a useful marker for an unexpected Java value.
  }
  return {type: 'unsupported', value: className};
}

function safeExtra(value, depth) {
  if (depth > 2) {
    return {type: 'unsupported', value: 'maximum nesting depth'};
  }
  if (value === null || value === undefined) {
    return tagged('null', null);
  }

  let className;
  try {
    className = String(value.getClass().getName());
  } catch (ignored) {
    return unsupported(value);
  }

  try {
    if (className === 'java.lang.String' ||
        className === 'java.lang.CharSequence') {
      const text = String(value.toString());
      return tagged('string', clipped(text, MAX_TEXT_LENGTH), text.length > MAX_TEXT_LENGTH);
    }
    if (className === 'java.lang.Boolean') {
      return tagged('boolean', !!value.booleanValue());
    }
    if (className === 'java.lang.Byte') {
      return tagged('byte', Number(value.byteValue()));
    }
    if (className === 'java.lang.Short') {
      return tagged('short', Number(value.shortValue()));
    }
    if (className === 'java.lang.Integer') {
      return tagged('int', Number(value.intValue()));
    }
    if (className === 'java.lang.Long') {
      return tagged('long', String(value.toString()));
    }
    if (className === 'java.lang.Float') {
      const number = Number(value.floatValue());
      return isFinite(number) ? tagged('float', number) : unsupported(value);
    }
    if (className === 'java.lang.Double') {
      const number = Number(value.doubleValue());
      return isFinite(number) ? tagged('double', number) : unsupported(value);
    }
    if (className === 'java.lang.Character') {
      return tagged('char', String(value.charValue()));
    }

    const valueClass = value.getClass();
    if (valueClass.isArray()) {
      const componentClass = valueClass.getComponentType();
      const componentName = String(componentClass.getName());
      if (!componentClass.isPrimitive() && componentName !== 'java.lang.String') {
        return unsupported(value);
      }
      const ReflectArray = Java.use('java.lang.reflect.Array');
      const fullLength = Number(ReflectArray.getLength(value));
      const arrayLength = Math.min(fullLength, MAX_ARRAY_ITEMS);
      const values = [];
      let itemType = null;
      for (let index = 0; index < arrayLength; index += 1) {
        const item = safeExtra(ReflectArray.get(value, index), depth + 1);
        if (item.type === 'unsupported' || item.type === 'null' ||
            (itemType !== null && item.type !== itemType)) {
          return unsupported(value);
        }
        itemType = item.type;
        values.push(item.value);
      }
      const primitiveArrayTypes = {
        boolean: 'boolean_array', byte: 'byte_array', short: 'short_array',
        int: 'int_array', long: 'long_array', float: 'float_array',
        double: 'double_array', char: 'char_array', string: 'string_array',
      };
      if (itemType === null || !primitiveArrayTypes[itemType]) {
        return unsupported(value);
      }
      return tagged(primitiveArrayTypes[itemType], values, fullLength > MAX_ARRAY_ITEMS);
    }

    if (className === 'android.net.Uri') {
      const text = String(value.toString());
      return tagged('uri', clipped(text, MAX_TEXT_LENGTH), text.length > MAX_TEXT_LENGTH);
    }
    if (className === 'android.content.ComponentName') {
      return tagged('component', {
        package: String(value.getPackageName()),
        class: String(value.getClassName()),
      });
    }
  } catch (error) {
    return {type: 'unsupported', value: className + ': ' + String(error)};
  }
  return {type: 'unsupported', value: className};
}

function readMaterializedExtras(bundle) {
  let map = null;
  try {
    const BaseBundle = Java.use('android.os.BaseBundle');
    map = Java.cast(bundle, BaseBundle).mMap.value;
  } catch (ignored) {
    // Fall through to reflection for Android releases where Frida does not
    // expose the framework field directly.
  }
  if (map === null) {
    try {
      let currentClass = bundle.getClass();
      while (currentClass !== null && map === null) {
        try {
          const field = currentClass.getDeclaredField('mMap');
          field.setAccessible(true);
          map = field.get(bundle);
        } catch (ignored) {
          currentClass = currentClass.getSuperclass();
        }
      }
    } catch (ignored) {
      return {values: {}, truncated: false, unavailable: true};
    }
  }
  if (map === null) {
    return {values: {}, truncated: false, unavailable: true};
  }

  const values = Object.create(null);
  let truncated = false;
  try {
    const iterator = map.entrySet().iterator();
    let count = 0;
    while (iterator.hasNext()) {
      if (count >= MAX_EXTRA_COUNT) {
        truncated = true;
        break;
      }
      const entry = iterator.next();
      const key = String(entry.getKey());
      try {
        values[key] = safeExtra(entry.getValue(), 0);
      } catch (error) {
        values[key] = {type: 'unsupported', value: String(error)};
      }
      count += 1;
    }
  } catch (ignored) {
    return {values: {}, truncated: false, unavailable: true};
  }
  return {values: values, truncated: truncated, unavailable: false};
}

const KNOWN_FLAGS = [
  [0x10000000, 'FLAG_ACTIVITY_NEW_TASK'],
  [0x04000000, 'FLAG_ACTIVITY_CLEAR_TOP'],
  [0x20000000, 'FLAG_ACTIVITY_SINGLE_TOP'],
  [0x08000000, 'FLAG_ACTIVITY_MULTIPLE_TASK'],
  [0x40000000, 'FLAG_ACTIVITY_NO_HISTORY'],
  [0x02000000, 'FLAG_ACTIVITY_FORWARD_RESULT'],
  [0x01000000, 'FLAG_ACTIVITY_PREVIOUS_IS_TOP'],
  [0x00800000, 'FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS'],
  [0x00400000, 'FLAG_ACTIVITY_BROUGHT_TO_FRONT'],
  [0x00100000, 'FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY'],
  [0x00080000, 'FLAG_ACTIVITY_NEW_DOCUMENT'],
  [0x00040000, 'FLAG_ACTIVITY_NO_USER_ACTION'],
  [0x00020000, 'FLAG_ACTIVITY_REORDER_TO_FRONT'],
  [0x00010000, 'FLAG_ACTIVITY_NO_ANIMATION'],
  [0x00008000, 'FLAG_ACTIVITY_CLEAR_TASK'],
  [0x00004000, 'FLAG_ACTIVITY_TASK_ON_HOME'],
];

function intentToObject(intent) {
  const component = intent.getComponent();
  const categories = [];
  const categorySet = intent.getCategories();
  if (categorySet !== null) {
    const iterator = categorySet.iterator();
    while (iterator.hasNext() && categories.length < MAX_EXTRA_COUNT) {
      categories.push(String(iterator.next()));
    }
  }

  const flags = Number(intent.getFlags()) | 0;
  const flagNames = [];
  KNOWN_FLAGS.forEach(function (entry) {
    if ((flags & entry[0]) !== 0) {
      flagNames.push(entry[1]);
    }
  });

  const bundle = intent.getExtras();
  const extrasResult = bundle === null
    ? {values: {}, truncated: false, unavailable: false}
    : readMaterializedExtras(bundle);

  const data = intent.getData();
  return {
    component: component === null ? null : {
      package: String(component.getPackageName()),
      class: String(component.getClassName()),
    },
    action: intent.getAction() === null ? null : clipped(intent.getAction(), MAX_TEXT_LENGTH),
    action_truncated: intent.getAction() !== null && String(intent.getAction()).length > MAX_TEXT_LENGTH,
    data: data === null ? null : clipped(data.toString(), MAX_TEXT_LENGTH),
    data_truncated: data !== null && String(data.toString()).length > MAX_TEXT_LENGTH,
    type: intent.getType() === null ? null : clipped(intent.getType(), MAX_TEXT_LENGTH),
    package: intent.getPackage() === null ? null : clipped(intent.getPackage(), MAX_TEXT_LENGTH),
    flags: flags,
    flags_hex: '0x' + (flags >>> 0).toString(16).padStart(8, '0'),
    flag_names: flagNames,
    categories: categories.map(function (category) { return clipped(category, MAX_TEXT_LENGTH); }),
    extras: extrasResult.values,
    extras_truncated: extrasResult.truncated,
    extras_unavailable: extrasResult.unavailable,
  };
}

const activeIntentHashes = Object.create(null);

function emitIntents(source, values, seenInCall, claimed) {
  values.forEach(function (intent) {
    if (intent === null || intent === undefined) {
      return;
    }
    try {
      const System = Java.use('java.lang.System');
      const key = String(System.identityHashCode(intent));
      if (activeIntentHashes[key] && !seenInCall[key]) {
        return;
      }
      if (!seenInCall[key]) {
        seenInCall[key] = true;
        activeIntentHashes[key] = true;
        claimed.push(key);
      }
      send({type: 'intent_started', source: source, intent: intentToObject(intent)});
    } catch (error) {
      send({type: 'intent_hook_warning', source: source, error: String(error)});
    }
  });
}

function hookIntentMethods(className, methodNames) {
  let clazz;
  try {
    clazz = Java.use(className);
  } catch (error) {
    return {installed: [], warning: className + ': ' + String(error)};
  }

  const installed = [];
  methodNames.forEach(function (methodName) {
    let method;
    try {
      method = clazz[methodName];
    } catch (ignored) {
      method = null;
    }
    if (method === null || method === undefined) {
      return;
    }

    method.overloads.forEach(function (overload) {
      const parameters = overload.argumentTypes;
      const intentIndexes = [];
      for (let index = 0; index < parameters.length; index += 1) {
        const typeName = String(parameters[index].className);
        if (typeName === 'android.content.Intent' ||
            typeName === '[Landroid.content.Intent;' ||
            typeName === 'android.content.Intent[]') {
          intentIndexes.push({index: index, array: typeName.indexOf('[]') !== -1 || typeName.charAt(0) === '['});
        }
      }
      if (intentIndexes.length === 0) {
        return;
      }

      overload.implementation = function () {
        const args = Array.prototype.slice.call(arguments);
        const seenInCall = Object.create(null);
        const claimed = [];
        intentIndexes.forEach(function (info) {
          try {
            if (info.array) {
              const ReflectArray = Java.use('java.lang.reflect.Array');
              const array = args[info.index];
              const length = Math.min(Number(ReflectArray.getLength(array)), MAX_ARRAY_ITEMS);
              const intents = [];
              for (let index = 0; index < length; index += 1) {
                intents.push(ReflectArray.get(array, index));
              }
              emitIntents(className + '.' + methodName, intents, seenInCall, claimed);
            } else {
              emitIntents(className + '.' + methodName, [args[info.index]], seenInCall, claimed);
            }
          } catch (error) {
            send({
              type: 'intent_hook_warning',
              source: className + '.' + methodName,
              error: String(error),
            });
          }
        });
        try {
          return overload.apply(this, args);
        } finally {
          claimed.forEach(function (key) {
            delete activeIntentHashes[key];
          });
        }
      };
      installed.push(methodName + '(' + intentIndexes.length + ' Intent argument(s))');
    });
  });
  return {installed: installed, warning: ''};
}

Java.perform(function () {
  try {
    if (!Java.available) {
      throw new Error('the target process has no Java VM');
    }

    const groups = [
      hookIntentMethods('android.app.Instrumentation', [
        'execStartActivity', 'execStartActivityAsCaller', 'execStartActivities',
        'execStartActivitiesAsUser',
      ]),
      hookIntentMethods('android.app.ContextImpl', ['startActivity', 'startActivities']),
    ];
    const installed = [];
    groups.forEach(function (group) {
      installed.push.apply(installed, group.installed);
      if (group.warning) {
        send({type: 'intent_hook_warning', error: group.warning});
      }
    });
    if (installed.length === 0) {
      send({type: 'intent_hook_warning', error: 'no Intent launch methods were available to hook'});
    }

    send({type: 'ready', mode: 'root', hooks: installed});
  } catch (error) {
    send({type: 'error', error: String(error)});
  }
});
