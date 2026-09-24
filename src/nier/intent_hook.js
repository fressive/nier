'use strict';

const MAX_EXTRA_COUNT = 100;
const MAX_ARRAY_ITEMS = 64;
const MAX_TEXT_LENGTH = 4096;

function clipped(value, limit) {
  const text = String(value);
  return text.length > limit ? text.slice(0, limit) + '…' : text;
}

function tagged(type, value) {
  return {type: type, value: value};
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
      return tagged('string', clipped(value.toString(), MAX_TEXT_LENGTH));
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
      return tagged('float', Number(value.floatValue()));
    }
    if (className === 'java.lang.Double') {
      return tagged('double', Number(value.doubleValue()));
    }
    if (className === 'java.lang.Character') {
      return tagged('char', String(value.charValue()));
    }

    const valueClass = value.getClass();
    if (valueClass.isArray()) {
      const ReflectArray = Java.use('java.lang.reflect.Array');
      const arrayLength = Math.min(
        Number(ReflectArray.getLength(value)),
        MAX_ARRAY_ITEMS
      );
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
      return tagged(primitiveArrayTypes[itemType], values);
    }

    if (className === 'android.net.Uri') {
      return tagged('uri', clipped(value.toString(), MAX_TEXT_LENGTH));
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

  const flags = Number(intent.getFlags());
  const flagNames = [];
  KNOWN_FLAGS.forEach(function (entry) {
    if ((flags & entry[0]) !== 0) {
      flagNames.push(entry[1]);
    }
  });

  const extras = {};
  const bundle = intent.getExtras();
  if (bundle !== null) {
    const keys = bundle.keySet().toArray();
    const count = Math.min(Number(keys.length), MAX_EXTRA_COUNT);
    for (let index = 0; index < count; index += 1) {
      const key = String(keys[index]);
      try {
        extras[key] = safeExtra(bundle.get(key), 0);
      } catch (error) {
        extras[key] = {type: 'unsupported', value: String(error)};
      }
    }
  }

  const data = intent.getData();
  return {
    component: component === null ? null : {
      package: String(component.getPackageName()),
      class: String(component.getClassName()),
    },
    action: intent.getAction() === null ? null : String(intent.getAction()),
    data: data === null ? null : clipped(data.toString(), MAX_TEXT_LENGTH),
    type: intent.getType() === null ? null : String(intent.getType()),
    package: intent.getPackage() === null ? null : String(intent.getPackage()),
    flags: flags,
    flags_hex: '0x' + (flags >>> 0).toString(16).padStart(8, '0'),
    flag_names: flagNames,
    categories: categories,
    extras: extras,
    extras_truncated: bundle !== null && Number(bundle.size()) > MAX_EXTRA_COUNT,
  };
}

function emitIntents(source, values) {
  values.forEach(function (intent) {
    if (intent === null || intent === undefined) {
      return;
    }
    try {
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
            typeName === '[Landroid.content.Intent;') {
          intentIndexes.push({index: index, array: typeName.charAt(0) === '['});
        }
      }
      if (intentIndexes.length === 0) {
        return;
      }

      overload.implementation = function () {
        const args = Array.prototype.slice.call(arguments);
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
              emitIntents(className + '.' + methodName, intents);
            } else {
              emitIntents(className + '.' + methodName, [args[info.index]]);
            }
          } catch (error) {
            send({
              type: 'intent_hook_warning',
              source: className + '.' + methodName,
              error: String(error),
            });
          }
        });
        return overload.apply(this, args);
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
        'execStartActivity', 'execStartActivities', 'execStartActivitiesAsUser',
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

    send({type: 'ready', mode: 'root', hooks: installed});
  } catch (error) {
    send({type: 'error', error: String(error)});
  }
});
