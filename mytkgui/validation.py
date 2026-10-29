"""Validation for view models (WPF's INotifyDataErrorInfo). No Tk here.

    class NewExpense(Validatable):
        description = observable("")
        amount = observable("")

        @validator("description")
        def _description(self, value):
            if not value.strip():
                return "Describe the expense."

        @validator("amount")
        def _amount(self, value):
            try:
                if float(value) <= 0:
                    return "Must be more than zero."
            except ValueError:
                return "Enter a number."

    form.is_valid              # every rule passes
    form.errors.amount         # message to show, "" if none (touched fields only)
    form.all_errors.amount     # message regardless of touched
    form.validate()            # show every error (e.g. on Save); returns is_valid

A bound field (``text="{form.amount}"``) marks itself touched when edited
and goes into the theme's *invalid* state while its field has a shown error.
Errors are computed values, so they follow the data like everything else.
"""

from .reactive import Observable, _takes_parameter, computed, untracked

__all__ = ["Validatable", "validator", "ErrorMap"]


def validator(*fields):
    """Marks a method as the rule for ``fields``. It returns a message, or
    None/"" when valid. It may take the (first) field's value or read ``self``."""
    def mark(fn):
        fn._validates = fields
        return fn
    return mark


class ErrorMap:
    """Field name -> message. Attribute access gives "" for a valid field,
    so views can bind ``{form.errors.amount}`` directly."""

    def __init__(self, messages):
        self._messages = dict(messages)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._messages.get(name, "")

    def __getitem__(self, name):
        return self._messages.get(name, "")

    def __bool__(self):
        return bool(self._messages)

    def __len__(self):
        return len(self._messages)

    def __iter__(self):
        return iter(self._messages)

    def __contains__(self, name):
        return name in self._messages

    def items(self):
        return self._messages.items()

    def __eq__(self, other):
        return isinstance(other, ErrorMap) and other._messages == self._messages

    def __repr__(self):
        return "ErrorMap(%r)" % (self._messages,)


def _rules(cls):
    rules = cls.__dict__.get("__validation_rules__")
    if rules is None:
        rules, seen = [], set()
        for klass in cls.__mro__:
            for name, value in vars(klass).items():
                if name not in seen and callable(value) and hasattr(value, "_validates"):
                    seen.add(name)
                    rules.append(value)
        cls.__validation_rules__ = rules
    return rules


class Validatable:
    """Mixin giving a view model ``errors``, ``all_errors``, ``is_valid``,
    ``validate()``, ``touch(field)`` and ``error_for(field)``."""

    def _validation_state(self):
        state = self.__dict__.get("__validation__")
        if state is None:
            state = self.__dict__["__validation__"] = (Observable(frozenset()), Observable(False))
        return state

    @computed
    def all_errors(self):
        messages = {}
        for rule in _rules(type(self)):
            fields = rule._validates
            if _takes_parameter(rule, 1):
                message = rule(self, getattr(self, fields[0]))
            else:
                message = rule(self)
            if message:
                for field in fields:
                    messages.setdefault(field, message)
        return ErrorMap(messages)

    @computed
    def errors(self):
        touched, show_all = (o.get() for o in self._validation_state())
        return ErrorMap({k: v for k, v in self.all_errors.items() if show_all or k in touched})

    @computed
    def is_valid(self):
        return not self.all_errors

    def error_for(self, field):
        """The message shown for ``field`` ("" if none)."""
        return self.errors[field]

    def touch(self, field):
        touched = self._validation_state()[0]
        with untracked():
            if field not in touched.get():
                touched.set(touched.get() | {field})

    def validate(self):
        """Show all errors (e.g. when the user presses Save); returns ``is_valid``."""
        with untracked():
            self._validation_state()[1].set(True)
            return self.is_valid

    def reset_validation(self):
        """Hide errors again (e.g. after the form is cleared)."""
        touched, show_all = self._validation_state()
        with untracked():
            touched.set(frozenset())
            show_all.set(False)
